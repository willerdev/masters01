from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.connectors.types import NormalizedQuote
from app.core.database import SessionLocal
from app.models.entities import Account, NakedLimit
from app.services.naked_limits import remind_naked_limits


def _auth(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "naked@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Naked"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _probe(method, credentials):
    return {
        "ok": True,
        "status": "connected",
        "error_code": "",
        "detail": "",
        "region": "london",
        "account": {
            "display_name": "Live book",
            "account_number": "550011",
            "broker": "Example",
            "server": "Example-Live",
            "currency": "USD",
            "leverage": "100",
            "balance": "10000",
            "equity": "10000",
            "margin": "0",
            "free_margin": "10000",
            "margin_level": None,
        },
    }


def _quote(self, credentials, symbol):
    return NormalizedQuote(symbol, Decimal("84.0000"), Decimal("84.0200"), Decimal("0.0200"), Decimal("0.0001"), datetime.now(timezone.utc), "metaapi")


def test_an_invalid_stop_is_dropped_and_the_limit_is_still_sent(client, monkeypatch):
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    account_id = created.json()["id"]
    sent = []

    def trade(self, credentials, body):
        sent.append(body)
        if "stopLoss" in body:
            return {
                "ok": False,
                "numeric_code": 10016,
                "string_code": "TRADE_RETCODE_INVALID_STOPS",
                "message": "Invalid stops in the request",
                "order_id": "",
                "position_id": "",
            }
        return {"ok": True, "numeric_code": 10009, "string_code": "DONE", "message": "done", "order_id": "77", "position_id": ""}

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_quote", _quote)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_symbol_spec", lambda self, credentials, symbol: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        headers=headers,
        json={
            "action": "limit",
            "symbol": "Volatility 50 (1s) Index",
            "side": "buy",
            "volume": "0.005",
            "price": "83.3586",
            "stop_loss": "82.4615",
            "take_profit": "88.6128",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is True
    assert "without a stop" in body["message"]
    assert "stopLoss" in sent[0]
    assert sent[0]["takeProfit"] == 88.6128
    assert "stopLoss" not in sent[1]
    assert sent[1]["takeProfit"] == 88.6128
    assert sent[1]["openPrice"] == 83.3586
    db = SessionLocal()
    try:
        row = db.query(NakedLimit).filter(NakedLimit.account_id == account_id).one()
        assert row.ticket == "77"
        assert row.ignored_stop == Decimal("82.4615")
    finally:
        db.close()


def test_the_reminder_repeats_every_five_minutes_until_the_stop_exists_or_the_order_is_gone(client, monkeypatch):
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    account_id = created.json()["id"]
    orders = [
        {
            "id": "77",
            "symbol": "Volatility 50 (1s) Index",
            "type": "ORDER_TYPE_BUY_LIMIT",
            "state": "ORDER_STATE_PLACED",
            "openPrice": 83.3586,
            "stopLoss": 0,
            "volume": 0.005,
        }
    ]
    sent = []
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_orders", lambda self, credentials: list(orders))
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", lambda self, credentials: [])
    monkeypatch.setattr("app.services.alert_service._telegram", lambda token, method, payload=None: sent.append(payload) or {"ok": True})
    monkeypatch.setattr(
        "app.services.alert_service._telegram_secret",
        lambda db, organization_id: {"bot_token": "123456789:AAHtesttokenvalueforthebot12345", "chat_id": "42"},
    )
    db = SessionLocal()
    try:
        account = db.get(Account, account_id)
        due = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.add(
            NakedLimit(
                organization_id=account.organization_id,
                account_id=account.id,
                ticket="77",
                symbol="Volatility 50 (1s) Index",
                side="buy",
                entry=Decimal("83.3586"),
                volume=Decimal("0.005"),
                ignored_stop=Decimal("82.4615"),
                last_reminded_at=due,
            )
        )
        db.commit()
        remind_naked_limits(db)
        db.commit()
        assert len(sent) == 1
        assert "still has no stop loss" in sent[0]["text"]
        assert "82.4615" in sent[0]["text"]
        remind_naked_limits(db)
        db.commit()
        assert len(sent) == 1
        row = db.query(NakedLimit).one()
        row.last_reminded_at = due
        orders[0]["stopLoss"] = 82.4615
        db.commit()
        remind_naked_limits(db)
        db.commit()
        assert len(sent) == 1
        assert db.query(NakedLimit).count() == 0
        db.add(
            NakedLimit(
                organization_id=account.organization_id,
                account_id=account.id,
                ticket="88",
                symbol="Volatility 50 (1s) Index",
                side="buy",
                entry=Decimal("83.3586"),
                volume=Decimal("0.005"),
                ignored_stop=Decimal("82.4615"),
                last_reminded_at=due,
            )
        )
        orders.clear()
        db.commit()
        remind_naked_limits(db)
        db.commit()
        assert db.query(NakedLimit).count() == 0
        assert len(sent) == 1
    finally:
        db.close()

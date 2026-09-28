from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.synthetic_lots import minimum_lot, pip_size, plan_protection
from app.connectors.types import NormalizedQuote
from app.core.database import SessionLocal
from app.models.entities import Account, NakedLimit, User
from app.services.order_service import place_order


def test_deriv_minimum_lots_come_from_the_published_table():
    assert minimum_lot("Volatility 50 (1s) Index") == Decimal("0.005")
    assert minimum_lot("Volatility 100 Index") == Decimal("1")
    assert minimum_lot("EURUSD") is None


def test_a_buy_without_a_stop_gets_100_pips_and_a_2r_target():
    pip = pip_size("Volatility 50 (1s) Index", None)
    assert pip == Decimal("0.01")
    stop, take, auto_stop, auto_target = plan_protection("buy", Decimal("84"), None, None, pip)
    assert stop == Decimal("83")
    assert take == Decimal("86")
    assert auto_stop and auto_target


def _probe(method, credentials):
    return {
        "ok": True,
        "status": "connected",
        "error_code": "",
        "detail": "",
        "region": "london",
        "account": {
            "display_name": "Live book",
            "account_number": "550012",
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


def test_a_rejected_automatic_stop_is_widened_to_300_pips_and_kept(client, monkeypatch):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "wider-stop@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Wider"},
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-2"}},
    )
    assert created.status_code == 200, created.text
    account_id = created.json()["id"]
    sent = []

    def trade(self, credentials, body):
        sent.append(body)
        if len(sent) == 1:
            return {
                "ok": False,
                "numeric_code": 10016,
                "string_code": "TRADE_RETCODE_INVALID_STOPS",
                "message": "Invalid stops in the request",
                "order_id": "",
                "position_id": "",
            }
        return {"ok": True, "numeric_code": 10009, "string_code": "DONE", "message": "done", "order_id": "91", "position_id": ""}

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_quote", _quote)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_symbol_spec", lambda self, credentials, symbol: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    db = SessionLocal()
    try:
        account = db.get(Account, account_id)
        user = db.query(User).filter(User.email == "wider-stop@tradeguard.example").one()
        result = place_order(
            db,
            user,
            account,
            {"action": "limit", "symbol": "Volatility 50 (1s) Index", "side": "buy", "price": "84"},
            actor="ai",
        )
        db.commit()
        assert db.query(NakedLimit).filter(NakedLimit.account_id == account_id).count() == 0
    finally:
        db.close()
    assert result["sent"] is True
    assert sent[0]["stopLoss"] == 83
    assert sent[0]["takeProfit"] == 86
    assert sent[0]["volume"] == 0.005
    assert sent[1]["stopLoss"] == 81
    assert sent[1]["takeProfit"] == 90
    assert len(sent) == 2
    assert "300 pips" in result["message"]

from decimal import Decimal
from uuid import UUID

from app.core.database import SessionLocal
from app.models.entities import Account, Position
from app.services.alert_service import _telegram_secret, _write_telegram_secret
from app.services.trade_watch import watch_open_trades


def test_a_running_trade_is_announced_once(client, monkeypatch):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "watch@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Watch"},
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    monkeypatch.setattr(
        "app.services.account_service.probe_connection",
        lambda method, credentials: {
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
        },
    )
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    saved = client.put(
        "/api/v1/telegram",
        headers=headers,
        json={"app_id": "12345678", "api_hash": "a" * 32, "bot_token": "123456789:AAHtesttokenvalueforthebot12345"},
    )
    assert saved.status_code == 200, saved.text
    calls = []

    def telegram(token, method, payload=None):
        calls.append(payload)
        return {"ok": True}

    monkeypatch.setattr("app.services.alert_service._telegram", telegram)
    modified = []

    def trade(self, credentials, body):
        modified.append(body)
        return {"ok": True, "numeric_code": 10009, "string_code": "DONE", "message": "done", "order_id": "", "position_id": "900"}

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    db = SessionLocal()
    try:
        account = db.get(Account, UUID(created.json()["id"]))
        secret = _telegram_secret(db, account.organization_id)
        secret["chat_id"] = "42"
        _write_telegram_secret(db, account.organization_id, secret)
        db.add(
            Position(
                account_id=account.id,
                ticket="900",
                symbol="Volatility 90 (1s) Index",
                side="buy",
                volume=Decimal("0.02"),
                entry_price=Decimal("100"),
                current_price=Decimal("110"),
                stop_loss=Decimal("90"),
                profit=Decimal("12.50"),
                status="open",
            )
        )
        db.commit()
        watch_open_trades(db, [account])
        db.commit()
        watch_open_trades(db, [account])
        db.commit()
    finally:
        db.close()
    assert len(calls) == 1
    assert calls[0]["chat_id"] == "42"
    assert "1:1" in calls[0]["text"]
    assert "partials" in calls[0]["text"]
    assert "breakeven" in calls[0]["text"]
    assert "stop was moved to the entry at 100" in calls[0]["text"]
    assert len(modified) == 1
    assert modified[0]["actionType"] == "POSITION_MODIFY"
    assert modified[0]["positionId"] == "900"
    assert modified[0]["stopLoss"] == 100


def test_a_failed_breakeven_still_sends_the_update_and_is_not_retried(client, monkeypatch):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "watch-fail@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Watch"},
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    monkeypatch.setattr(
        "app.services.account_service.probe_connection",
        lambda method, credentials: {
            "ok": True,
            "status": "connected",
            "error_code": "",
            "detail": "",
            "region": "london",
            "account": {"display_name": "Live book", "account_number": "550013", "broker": "Example", "server": "Example-Live", "currency": "USD", "leverage": "100", "balance": "10000", "equity": "10000", "margin": "0", "free_margin": "10000", "margin_level": None},
        },
    )
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-3"}},
    )
    assert created.status_code == 200, created.text
    saved = client.put(
        "/api/v1/telegram",
        headers=headers,
        json={"app_id": "12345678", "api_hash": "a" * 32, "bot_token": "123456789:AAHtesttokenvalueforthebot12345"},
    )
    assert saved.status_code == 200, saved.text
    calls = []
    monkeypatch.setattr("app.services.alert_service._telegram", lambda token, method, payload=None: calls.append(payload) or {"ok": True})
    attempts = []

    def trade(self, credentials, body):
        attempts.append(body)
        raise RuntimeError("broker offline")

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    db = SessionLocal()
    try:
        account = db.get(Account, UUID(created.json()["id"]))
        secret = _telegram_secret(db, account.organization_id)
        secret["chat_id"] = "42"
        _write_telegram_secret(db, account.organization_id, secret)
        db.add(
            Position(
                account_id=account.id,
                ticket="901",
                symbol="Volatility 90 (1s) Index",
                side="sell",
                volume=Decimal("0.02"),
                entry_price=Decimal("100"),
                current_price=Decimal("90"),
                stop_loss=Decimal("110"),
                profit=Decimal("12.50"),
                status="open",
            )
        )
        db.commit()
        for _ in range(3):
            watch_open_trades(db, [account])
            db.commit()
    finally:
        db.close()
    assert len(attempts) == 1
    assert len(calls) == 1
    assert "1:1" in calls[0]["text"]
    assert "stop was not moved to the entry" in calls[0]["text"]

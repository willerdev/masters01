from decimal import Decimal

from app.core.database import SessionLocal
from app.models.entities import Account, SetupWatch, User
from app.services.setup_watch import consider_setup, watch_setups


def _book(client, monkeypatch, email: str, *, allow_trade: bool):
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
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Setups"},
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    if allow_trade:
        enabled = client.patch(f"/api/v1/accounts/{created.json()['id']}", headers=headers, json={"ai_trading_enabled": True})
        assert enabled.status_code == 200, enabled.text
    return created.json()["id"]


def test_a_setup_without_stop_or_target_gets_100_pips_and_2r(client, monkeypatch):
    _book(client, monkeypatch, "setup-missing@tradeguard.example", allow_trade=True)
    calls = []

    def place(db, user, account, payload, actor="user"):
        calls.append(payload)
        return {"sent": True, "message": "Limit accepted"}

    monkeypatch.setattr("app.services.order_service.place_order", place)
    monkeypatch.setattr(
        "app.services.ai_service.extract_signal",
        lambda db, organization_id, text: {"symbol": "Volatility 50 (1s) Index", "side": "buy", "entry": Decimal("84"), "stop_loss": None, "take_profit": None, "volume": None},
    )
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "setup-missing@tradeguard.example").one()
        reply = consider_setup(db, user.organization_id, "42", "Buy Volatility 50 (1s) entry 84")
        db.commit()
    finally:
        db.close()
    assert reply is not None and "Limit set" in reply and "100 pips" in reply
    assert calls[0]["price"] == Decimal("84")
    assert calls[0]["stop_loss"] == Decimal("83")
    assert calls[0]["take_profit"] == Decimal("86")
    assert calls[0]["volume"] == Decimal("0.005")


def test_an_ordinary_instruction_without_a_stop_is_left_for_deepseek(client, monkeypatch):
    _book(client, monkeypatch, "setup-plain@tradeguard.example", allow_trade=True)
    calls = []
    monkeypatch.setattr("app.services.order_service.place_order", lambda *args, **kwargs: calls.append(args) or {"sent": True, "message": "ok"})
    monkeypatch.setattr(
        "app.services.ai_service.extract_signal",
        lambda db, organization_id, text: {"symbol": "EURUSD", "side": "buy", "entry": Decimal("1.0850"), "stop_loss": None, "take_profit": None, "volume": None},
    )
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "setup-plain@tradeguard.example").one()
        reply = consider_setup(db, user.organization_id, "42", "buy eurusd now")
        db.commit()
    finally:
        db.close()
    assert reply is None
    assert calls == []


def test_a_complete_setup_sets_the_limit_with_entry_stop_and_target(client, monkeypatch):
    account_id = _book(client, monkeypatch, "setup-complete@tradeguard.example", allow_trade=True)
    calls = []

    def place(db, user, account, payload, actor="user"):
        calls.append(payload)
        return {"sent": True, "message": "Limit accepted"}

    monkeypatch.setattr("app.services.order_service.place_order", place)
    monkeypatch.setattr(
        "app.services.ai_service.extract_signal",
        lambda db, organization_id, text: {
            "symbol": "Volatility 75 Index",
            "side": "buy",
            "entry": Decimal("20405.42"),
            "stop_loss": Decimal("20247.38"),
            "take_profit": Decimal("20885.61"),
            "volume": Decimal("0.01"),
        },
    )
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "setup-complete@tradeguard.example").one()
        reply = consider_setup(db, user.organization_id, "42", "waiting for this buy")
        db.commit()
        row = db.query(SetupWatch).filter(SetupWatch.organization_id == user.organization_id).one()
        assert row.order_sent is True
        assert row.account_id is not None
        assert str(row.account_id) == account_id
    finally:
        db.close()
    assert "Limit set" in reply
    assert calls[0]["action"] == "limit"
    assert calls[0]["price"] == Decimal("20405.42")
    assert calls[0]["stop_loss"] == Decimal("20247.38")
    assert calls[0]["take_profit"] == Decimal("20885.61")
    assert calls[0]["symbol"] == "Volatility 75 Index"


def test_price_reaching_the_entry_notifies_once_and_enters_only_when_allowed(client, monkeypatch):
    _book(client, monkeypatch, "setup-watch@tradeguard.example", allow_trade=False)
    placed = []
    monkeypatch.setattr("app.services.order_service.place_order", lambda *args, **kwargs: placed.append(True) or {"sent": True, "message": "ok"})
    monkeypatch.setattr(
        "app.services.ai_service.extract_signal",
        lambda db, organization_id, text: {
            "symbol": "EURUSD",
            "side": "buy",
            "entry": Decimal("1.0850"),
            "stop_loss": Decimal("1.0800"),
            "take_profit": Decimal("1.0950"),
            "volume": Decimal("0.01"),
        },
    )
    sent = []
    monkeypatch.setattr("app.services.alert_service._telegram", lambda token, method, payload=None: sent.append(payload) or {"ok": True})
    monkeypatch.setattr("app.services.alert_service._telegram_secret", lambda db, organization_id: {"bot_token": "123456789:AAHtesttokenvalueforthebot12345", "chat_id": "42"})
    prices = {"ask": "1.0900"}
    monkeypatch.setattr("app.services.order_service.read_price", lambda db, account, symbol: {"symbol": symbol, "bid": "1.0898", "ask": prices["ask"]})
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "setup-watch@tradeguard.example").one()
        reply = consider_setup(db, user.organization_id, "42", "Buy EURUSD entry 1.0850 stop 1.0800 target 1.0950")
        db.commit()
        account = db.query(Account).filter(Account.organization_id == user.organization_id).one()
        watch_setups(db, [account])
        db.commit()
        assert sent == []
        prices["ask"] = "1.0850"
        watch_setups(db, [account])
        db.commit()
        watch_setups(db, [account])
        db.commit()
        row = db.query(SetupWatch).filter(SetupWatch.organization_id == user.organization_id).one()
        assert row.order_sent is False
        assert row.notified is True
        assert row.status == "reached"
    finally:
        db.close()
    assert "did not send the limit" in reply
    assert placed == []
    assert len(sent) == 1
    assert "Price reached 1.085" in sent[0]["text"]
    assert "did not enter" in sent[0]["text"]

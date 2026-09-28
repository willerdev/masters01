import asyncio
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from telethon.errors import SessionPasswordNeededError

from app.core.database import SessionLocal
from app.models.entities import TelegramConfig
from app.services.alert_service import _telegram_secret, _write_telegram_secret
from app.models.entities import PendingSignal
from app.services.ai_service import parse_signal_reply
from app.services.telegram_user import CopiedMessage, drain_copied_signals, expire_pending_signals, _signal_text


def _auth(client, email):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _save_bot(client, token):
    saved = client.put(
        "/api/v1/telegram",
        headers=_headers(token),
        json={"app_id": "12345678", "api_hash": "a" * 32, "bot_token": "123456789:AAHtesttokenvalueforthebot12345"},
    )
    assert saved.status_code == 200, saved.text


def _config(db):
    row = db.scalar(select(TelegramConfig))
    assert row is not None
    return row


def test_login_code_and_password_stay_off_the_response(client, monkeypatch):
    token = _auth(client, "telegram-login@tradeguard.example")
    _save_bot(client, token)

    class Client:
        async def is_user_authorized(self):
            return False

        async def send_code_request(self, phone):
            return SimpleNamespace(phone_code_hash="hash-secret-value")

        async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
            if password != "cloud-secret":
                raise SessionPasswordNeededError(None)
            return object()

        async def get_me(self):
            return object()

    def connect(app_id, api_hash, session, worker):
        return asyncio.run(worker(Client())), "session-secret-value"

    monkeypatch.setattr("app.services.telegram_user._connect", connect)
    sent = client.post("/api/v1/telegram/user/code", headers=_headers(token), json={"phone": "+1 555 123 0000"})
    assert sent.status_code == 200, sent.text
    assert sent.json() == {"sent": True, "connected": False}
    assert "hash-secret-value" not in sent.text
    assert "session-secret-value" not in sent.text
    missing = client.post("/api/v1/telegram/user/confirm", headers=_headers(token), json={"code": "12345", "password": ""})
    assert missing.status_code == 400, missing.text
    assert "cloud password" in missing.json()["detail"]
    confirmed = client.post(
        "/api/v1/telegram/user/confirm",
        headers=_headers(token),
        json={"code": "12345", "password": "cloud-secret"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json() == {"connected": True}
    assert "session-secret-value" not in confirmed.text
    assert "cloud-secret" not in confirmed.text
    db = SessionLocal()
    try:
        saved = _telegram_secret(db, _config(db).organization_id)
    finally:
        db.close()
    assert saved["user_session"] == "session-secret-value"
    assert saved["user_connected"] is True
    assert "phone_code_hash" not in saved
    assert "phone" not in saved
    forgotten = client.delete("/api/v1/telegram/user", headers=_headers(token))
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json() == {"connected": False}
    db = SessionLocal()
    try:
        saved = _telegram_secret(db, _config(db).organization_id)
    finally:
        db.close()
    assert "user_session" not in saved
    assert saved["app_id"] == "12345678"
    assert saved["bot_token"].startswith("123456789:")


def test_saving_the_bot_keeps_the_telegram_login(client):
    token = _auth(client, "telegram-keep@tradeguard.example")
    _save_bot(client, token)
    db = SessionLocal()
    try:
        row = _config(db)
        saved = _telegram_secret(db, row.organization_id)
        saved["user_session"] = "session-secret-value"
        saved["user_connected"] = True
        saved["phone_code_hash"] = "hash-secret-value"
        saved["copy_chats"] = [{"id": "-100", "title": "Signals", "type": "channel", "peer": {"kind": "channel", "id": 100, "access_hash": 1}}]
        saved["copy_cursors"] = {"-100": 50}
        _write_telegram_secret(db, row.organization_id, saved)
        db.commit()
    finally:
        db.close()
    again = client.put(
        "/api/v1/telegram",
        headers=_headers(token),
        json={"app_id": "12345678", "api_hash": "", "bot_token": ""},
    )
    assert again.status_code == 200, again.text
    assert "session-secret-value" not in again.text
    assert "hash-secret-value" not in again.text
    db = SessionLocal()
    try:
        saved = _telegram_secret(db, _config(db).organization_id)
    finally:
        db.close()
    assert saved["user_session"] == "session-secret-value"
    assert saved["phone_code_hash"] == "hash-secret-value"
    assert saved["copy_chats"][0]["id"] == "-100"
    assert saved["copy_cursors"]["-100"] == 50
    assert saved["bot_token"].startswith("123456789:")


def test_a_new_signal_is_traded_once_and_older_chats_are_not(client, monkeypatch):
    token = _auth(client, "telegram-copy@tradeguard.example")
    headers = _headers(token)
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
    enabled = client.patch(f"/api/v1/accounts/{created.json()['id']}", headers=headers, json={"ai_trading_enabled": True})
    assert enabled.status_code == 200, enabled.text
    _save_bot(client, token)
    db = SessionLocal()
    try:
        row = _config(db)
        saved = _telegram_secret(db, row.organization_id)
        saved["user_session"] = "session-secret-value"
        saved["user_connected"] = True
        saved["chat_id"] = "42"
        _write_telegram_secret(db, row.organization_id, saved)
        db.commit()
    finally:
        db.close()

    def load_dialogs(saved):
        return (
            [{"id": "-100", "title": "Signals", "type": "channel", "peer": {"kind": "channel", "id": 100, "access_hash": 99}}],
            {"-100": 50},
            "session-secret-value",
        )

    monkeypatch.setattr("app.services.telegram_user._load_dialogs", load_dialogs)
    chosen = client.put("/api/v1/telegram/chats", headers=headers, json={"chat_ids": ["-100"]})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["chats"] == [{"id": "-100", "title": "Signals", "type": "channel", "selected": True}]
    assert "access_hash" not in chosen.text
    assert "session-secret-value" not in chosen.text
    def extract(db, organization_id, text):
        if "buy 0.01 VIX 75" not in text:
            return None
        return {"symbol": "Volatility 75 Index", "side": "buy", "entry": Decimal("13455"), "stop_loss": None, "take_profit": None, "volume": Decimal("0.01")}

    calls = []

    def telegram(bot_token, method, payload=None):
        calls.append((method, payload))
        return {"ok": True, "result": {}}

    def fetch(saved):
        cursor = int((saved.get("copy_cursors") or {}).get("-100") or 0)
        rows = [CopiedMessage("-200", "Other", 9, "ignore me"), CopiedMessage("42", "Bot", 3, "close ticket 1")]
        if cursor < 51:
            rows.append(CopiedMessage("-100", "Signals", 50, "old signal"))
            rows.append(CopiedMessage("-100", "Signals", 51, "buy 0.01 VIX 75"))
        return rows, "session-secret-value", True

    monkeypatch.setattr("app.services.ai_service.extract_signal", extract)
    monkeypatch.setattr("app.services.alert_service._telegram", telegram)
    monkeypatch.setattr("app.services.telegram_user._fetch_updates", fetch)
    db = SessionLocal()
    try:
        drain_copied_signals(db)
        db.commit()
        drain_copied_signals(db)
        db.commit()
        saved = _telegram_secret(db, _config(db).organization_id)
    finally:
        db.close()
    sent = [payload for method, payload in calls if method == "sendMessage"]
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "42"
    assert "Pending buy Volatility 75 Index" in sent[0]["text"]
    assert "Auto execute is off" in sent[0]["text"]
    assert "old signal" not in sent[0]["text"]
    assert "ignore me" not in sent[0]["text"]
    listed = client.get("/api/v1/telegram/signals", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["auto_execute"] is False
    assert listed.json()["signals"][0]["symbol"] == "Volatility 75 Index"
    assert listed.json()["signals"][0]["entry"] == "13455"
    assert saved["copy_cursors"]["-100"] == 51
    assert saved["user_session"] == "session-secret-value"


def test_a_signal_photo_uses_the_saved_openai_key(monkeypatch):
    item = CopiedMessage("-100", "Signals", 8, "caption", b"img")
    monkeypatch.setattr("app.services.ai_service.openai_api_key", lambda db, org: "")
    assert _signal_text(None, None, "Signals", item) == "caption"
    monkeypatch.setattr("app.services.ai_service.openai_api_key", lambda db, org: "key")
    monkeypatch.setattr("app.services.ai_service.describe_image", lambda key, image, mime, caption: "buy volatility 75")
    assert _signal_text(None, None, "Signals", item) == "caption\n\nImage: buy volatility 75"
    photo = CopiedMessage("-100", "Signals", 9, "", b"img")
    monkeypatch.setattr("app.services.ai_service.openai_api_key", lambda db, org: "")
    assert _signal_text(None, None, "Signals", photo) == ""


def test_a_message_without_entry_is_not_a_signal():
    assert parse_signal_reply('{"signal": false}') is None
    assert parse_signal_reply('{"signal": true, "symbol": "EURUSD", "side": "buy"}') is None
    found = parse_signal_reply('{"signal": true, "symbol": "EURUSD", "side": "long", "entry": 1.085, "stop_loss": null, "volume": null}')
    assert found["symbol"] == "EURUSD"
    assert found["side"] == "buy"
    assert found["entry"] == Decimal("1.085")
    assert found["stop_loss"] is None
    assert found["volume"] is None


def test_pending_signals_expire_after_ten_minutes(client):
    token = _auth(client, "telegram-expire@tradeguard.example")
    _save_bot(client, token)
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        org = _config(db).organization_id
        db.add(PendingSignal(organization_id=org, chat_id="-100", chat_title="Signals", message_id=1, symbol="EURUSD", side="buy", entry=Decimal("1.1"), volume=Decimal("0.01"), created_at=now - timedelta(minutes=11)))
        db.add(PendingSignal(organization_id=org, chat_id="-100", chat_title="Signals", message_id=2, symbol="EURUSD", side="buy", entry=Decimal("1.1"), volume=Decimal("0.01"), created_at=now - timedelta(minutes=2)))
        db.commit()
        expire_pending_signals(db, org)
        db.commit()
        left = db.scalars(select(PendingSignal).where(PendingSignal.organization_id == org)).all()
    finally:
        db.close()
    assert [row.message_id for row in left] == [2]


def test_auto_execute_sends_the_limit_and_clears_the_pending_row(client, monkeypatch):
    token = _auth(client, "telegram-auto@tradeguard.example")
    headers = _headers(token)
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
    assert client.patch(f"/api/v1/accounts/{created.json()['id']}", headers=headers, json={"ai_trading_enabled": True}).status_code == 200
    _save_bot(client, token)
    db = SessionLocal()
    try:
        row = _config(db)
        saved = _telegram_secret(db, row.organization_id)
        saved.update({"user_session": "session-secret-value", "user_connected": True, "chat_id": "42", "auto_execute": True, "copy_chats": [{"id": "-100", "title": "Signals"}], "copy_cursors": {"-100": 1}})
        _write_telegram_secret(db, row.organization_id, saved)
        db.commit()
    finally:
        db.close()
    orders = []

    def place(db, user, account, payload, actor="user"):
        orders.append((payload, actor))
        return {"sent": True, "message": "done", "decision": "ALLOW"}

    monkeypatch.setattr("app.services.order_service.place_order", place)
    monkeypatch.setattr(
        "app.services.ai_service.extract_signal",
        lambda db, organization_id, text: {"symbol": "EURUSD", "side": "buy", "entry": Decimal("1.085"), "stop_loss": None, "take_profit": Decimal("1.09"), "volume": Decimal("0.02")},
    )
    monkeypatch.setattr("app.services.alert_service._telegram", lambda bot_token, method, payload=None: {"ok": True, "result": {}})
    monkeypatch.setattr(
        "app.services.telegram_user._fetch_updates",
        lambda saved: ([CopiedMessage("-100", "Signals", 2, "buy eurusd 1.085 tp 1.09")], "session-secret-value", True),
    )
    db = SessionLocal()
    try:
        drain_copied_signals(db)
        db.commit()
        left = db.scalars(select(PendingSignal)).all()
    finally:
        db.close()
    assert left == []
    assert orders[0][1] == "ai"
    assert orders[0][0]["action"] == "limit"
    assert orders[0][0]["symbol"] == "EURUSD"
    assert orders[0][0]["price"] == Decimal("1.085")
    assert orders[0][0]["take_profit"] == Decimal("1.09")
    assert orders[0][0]["stop_loss"] is None
    assert orders[0][0]["source"] == "Signals"

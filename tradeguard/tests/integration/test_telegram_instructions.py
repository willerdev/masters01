from app.core.database import SessionLocal
from app.services.alert_service import drain_telegram_trades


def _auth(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "telegram-trade@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Telegram"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_a_telegram_instruction_is_sent_to_deepseek(client, monkeypatch):
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
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
    account_id = created.json()["id"]
    enabled = client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"ai_trading_enabled": True})
    assert enabled.status_code == 200, enabled.text
    saved = client.put(
        "/api/v1/telegram",
        headers=headers,
        json={"app_id": "12345678", "api_hash": "a" * 32, "bot_token": "123456789:AAHtesttokenvalueforthebot12345"},
    )
    assert saved.status_code == 200, saved.text
    seen = []

    def assistant(db, user, account, message, images=None, source="DeepSeek", history=None):
        seen.append((account.id, message, source, history))
        return {"reply": "Closed 9001.", "steps": [{"tool": "close_trade", "result": {"sent": True, "decision": "ALLOW", "message": "done"}}]}

    calls = []

    def telegram(bot_token, method, payload=None):
        calls.append((method, payload))
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": ""}}
        if method == "getUpdates":
            if payload and payload.get("offset"):
                return {"ok": True, "result": []}
            return {"ok": True, "result": [{"update_id": 5, "message": {"text": "close ticket 9001", "chat": {"id": 42, "type": "private"}}}]}
        return {"ok": True, "result": {}}

    monkeypatch.setattr("app.services.ai_service.run_trade_assistant", assistant)
    monkeypatch.setattr("app.services.alert_service._telegram", telegram)
    db = SessionLocal()
    try:
        drain_telegram_trades(db)
        db.commit()
        drain_telegram_trades(db)
        db.commit()
    finally:
        db.close()
    assert seen == [(seen[0][0], "close ticket 9001", "Telegram", [])]
    sent = [payload for method, payload in calls if method == "sendMessage"]
    assert sent[0]["chat_id"] == "42"
    assert "Closed 9001." in sent[0]["text"]
    assert "close_trade: sent" in sent[0]["text"]
    assert len(sent) == 1


def test_a_follow_up_keeps_the_chart_reading(client, monkeypatch):
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
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
    account_id = created.json()["id"]
    enabled = client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"ai_trading_enabled": True})
    assert enabled.status_code == 200, enabled.text
    saved = client.put(
        "/api/v1/telegram",
        headers=headers,
        json={"app_id": "12345678", "api_hash": "a" * 32, "bot_token": "123456789:AAHtesttokenvalueforthebot12345"},
    )
    assert saved.status_code == 200, saved.text
    reading = "Buy Volatility 90 (1s) Index. Entry 20405.4228. Stop 20247.3899. Target 20885.6165."
    seen = []
    pending = [
        {"update_id": 5, "message": {"photo": [{"file_id": "chart-file"}], "caption": "", "chat": {"id": 42, "type": "private"}}},
        {"update_id": 6, "message": {"text": "set limit for buy for that", "chat": {"id": 42, "type": "private"}}},
    ]

    def assistant(db, user, account, message, images=None, source="DeepSeek", history=None):
        seen.append((message, history))
        return {"reply": "Buy limit sent.", "steps": []}

    def telegram(bot_token, method, payload=None):
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": ""}}
        if method == "getUpdates":
            if not pending:
                return {"ok": True, "result": []}
            item = pending.pop(0)
            if payload and payload.get("offset") and item["update_id"] < payload["offset"]:
                return {"ok": True, "result": []}
            return {"ok": True, "result": [item]}
        return {"ok": True, "result": {}}

    monkeypatch.setattr("app.services.ai_service.run_trade_assistant", assistant)
    monkeypatch.setattr("app.services.ai_service.openai_api_key", lambda db, organization_id: "sk-test")
    monkeypatch.setattr("app.services.ai_service.describe_image", lambda key, image, mime, caption: reading)
    monkeypatch.setattr("app.services.alert_service._telegram_file", lambda token, file_id: (b"img", "image/jpeg"))
    monkeypatch.setattr("app.services.alert_service._telegram", telegram)
    db = SessionLocal()
    try:
        drain_telegram_trades(db)
        db.commit()
        drain_telegram_trades(db)
        db.commit()
    finally:
        db.close()
    assert seen[0][0] == "set limit for buy for that"
    assert seen[0][1][0]["content"] == "Sent a chart image."
    assert reading in seen[0][1][1]["content"]

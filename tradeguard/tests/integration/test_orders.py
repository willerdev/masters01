from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.normalize import normalize_position
from app.connectors.types import NormalizedQuote


def _auth(client, email="orders@tradeguard.example"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Orders"},
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


def _position():
    return normalize_position(
        {
            "ticket": "9001",
            "symbol": "EURUSD",
            "side": "buy",
            "volume": "0.10",
            "entry_price": "1.10000",
            "current_price": "1.10100",
            "profit": "10",
        }
    )


def _account(client, monkeypatch, headers):
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _quote(self, credentials, symbol):
    return NormalizedQuote(symbol, Decimal("1.10000"), Decimal("1.10020"), Decimal("0.00020"), Decimal("0.00001"), datetime.now(timezone.utc), "metaapi")


def test_a_blocked_open_does_not_call_metaapi(client, monkeypatch):
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    turned_on = client.put(
        f"/api/v1/accounts/{account_id}/risk-rules",
        headers=headers,
        json={"enabled": {"max_lot": True}},
    )
    assert turned_on.status_code == 200, turned_on.text
    sent = []
    def offline_spec(self, credentials, symbol):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_quote", _quote)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_symbol_spec", offline_spec)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", lambda self, credentials, body: sent.append(body) or {"ok": True, "numeric_code": 10009, "message": "done", "order_id": "1", "position_id": "1", "string_code": "DONE"})
    response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        headers=headers,
        json={"action": "open", "symbol": "EURUSD", "side": "buy", "volume": "1.00"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is False
    assert body["decision"] == "BLOCK"
    assert any(hit["code"] == "MAX_LOT" for hit in body["hits"])
    assert sent == []
    assert "metaapi-token-value" not in response.text


def test_paused_risk_blocks_still_send_the_order(client, monkeypatch):
    token = _auth(client, email="pause@tradeguard.example")
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    turned_on = client.put(
        f"/api/v1/accounts/{account_id}/risk-rules",
        headers=headers,
        json={"enabled": {"max_lot": True}},
    )
    assert turned_on.status_code == 200, turned_on.text
    sent = []

    def offline_spec(self, credentials, symbol):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_quote", _quote)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_symbol_spec", offline_spec)
    monkeypatch.setattr(
        "app.connectors.metaapi.MetaApiConnector.trade",
        lambda self, credentials, body: sent.append(body) or {"ok": True, "numeric_code": 10009, "message": "done", "order_id": "2", "position_id": "2", "string_code": "DONE"},
    )
    paused = client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"risk_blocks_paused": True})
    assert paused.status_code == 200, paused.text
    assert paused.json()["risk_blocks_paused"] is True
    response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        headers=headers,
        json={"action": "open", "symbol": "EURUSD", "side": "buy", "volume": "1.00"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is True
    assert body["decision"] == "BLOCK"
    assert body["risk_blocks_paused"] is True
    assert sent[0]["symbol"] == "EURUSD"
    assert sent[0]["comment"] == "Desk"
    assert "metaapi-token-value" not in response.text


def test_breakeven_sends_the_open_price_as_the_stop(client, monkeypatch):
    token = _auth(client, email="be@tradeguard.example")
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", lambda self, credentials: [_position()])
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_account", lambda self, credentials: None)
    listed = client.get("/api/v1/trades", headers=headers)
    assert listed.json()["trades"][0]["ticket"] == "9001"
    sent = []

    def trade(self, credentials, body):
        sent.append(body)
        return {"ok": True, "numeric_code": 10009, "string_code": "TRADE_RETCODE_DONE", "message": "done", "order_id": "7", "position_id": "9001"}

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        headers=headers,
        json={"action": "breakeven", "ticket": "9001"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sent"] is True
    assert sent[0]["actionType"] == "POSITION_MODIFY"
    assert sent[0]["positionId"] == "9001"
    assert Decimal(str(sent[0]["stopLoss"])) == Decimal("1.1")
    assert "metaapi-token-value" not in response.text


def test_deepseek_close_tool_is_refused_when_the_switch_is_off(client, monkeypatch):
    token = _auth(client, email="ai-trade@tradeguard.example")
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", lambda self, credentials: [_position()])
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_account", lambda self, credentials: None)
    assert client.get("/api/v1/trades", headers=headers).status_code == 200
    saved = client.put(
        "/api/v1/ai/config",
        headers=headers,
        json={"provider": "deepseek", "enabled": True, "api_key": "sk-test"},
    )
    assert saved.status_code == 200, saved.text
    calls = {"chat": 0}
    sent = []

    def chat(self, model, temperature, max_tokens, messages, tools=None):
        calls["chat"] += 1
        if calls["chat"] == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "close_trade", "arguments": "{\"ticket\": \"9001\"}"}}],
            }
        return {"role": "assistant", "content": "Closed 9001."}

    def trade(self, credentials, body):
        sent.append(body)
        return {"ok": True, "numeric_code": 10009, "string_code": "DONE", "message": "done", "order_id": "8", "position_id": "9001"}

    monkeypatch.setattr("app.services.ai_service.DeepSeekProvider.chat", chat)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    enabled = client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"ai_trading_enabled": True})
    assert enabled.status_code == 200, enabled.text
    first = client.post(f"/api/v1/accounts/{account_id}/ai/trade", headers=headers, json={"message": "Close ticket 9001"})
    assert first.status_code == 200, first.text
    assert first.json()["reply"] == "Closed 9001."
    assert first.json()["steps"][0]["tool"] == "close_trade"
    assert sent[0]["actionType"] == "POSITION_CLOSE_ID"
    assert sent[0]["positionId"] == "9001"
    assert "sk-test" not in first.text
    disabled = client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"ai_trading_enabled": False})
    assert disabled.status_code == 200, disabled.text
    second = client.post(f"/api/v1/accounts/{account_id}/ai/trade", headers=headers, json={"message": "Close it again"})
    assert second.status_code == 403
    assert len(sent) == 1
    assert calls["chat"] == 2


def test_close_ai_trading_uses_the_app_id_and_api_key(client, monkeypatch):
    token = _auth(client, "close-ai@tradeguard.example")
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    sent = []

    def inspect(self, credentials, client=None):
        assert credentials["token"] == "trade-key-value"
        assert credentials["metaapi_account_id"] == "account-id-1"
        return _probe(None, None)

    def trade(self, credentials, body):
        sent.append(body)
        return {"ok": True, "numeric_code": 10009, "string_code": "DONE", "message": "done", "order_id": "3", "position_id": "9001"}

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.inspect", inspect)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", lambda self, credentials: [_position()])
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", trade)
    client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"ai_trading_enabled": True})
    response = client.post(
        f"/api/v1/accounts/{account_id}/ai/close",
        headers=headers,
        json={"app_id": "account-id-1", "api_key": "trade-key-value"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_trading_enabled"] is False
    assert body["closed_tickets"] == ["9001"]
    assert body["failed"] == []
    assert sent[0]["actionType"] == "POSITION_CLOSE_ID"
    assert sent[0]["positionId"] == "9001"
    assert "trade-key-value" not in response.text
    account = client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert account.json()["ai_trading_enabled"] is False


def test_close_ai_trading_rejects_a_bad_key(client, monkeypatch):
    token = _auth(client, "close-ai-bad@tradeguard.example")
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    called = []
    monkeypatch.setattr(
        "app.connectors.metaapi.MetaApiConnector.inspect",
        lambda self, credentials, client=None: {
            "ok": False,
            "status": "rejected",
            "error_code": "metaapi_unauthorized",
            "detail": "MetaAPI rejected the token",
            "region": "",
            "account": None,
        },
    )
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", lambda self, credentials, body: called.append(body))
    response = client.post(
        f"/api/v1/accounts/{account_id}/ai/close",
        headers=headers,
        json={"app_id": "account-id-1", "api_key": "wrong-key"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The trading API rejected that API secret"
    assert called == []
    assert "wrong-key" not in response.text


def test_bot_token_contacts_the_desk_and_closes(client, monkeypatch):
    token = _auth(client, "bot-close@tradeguard.example")
    headers = {"Authorization": f"Bearer {token}"}
    account_id = _account(client, monkeypatch, headers)
    sent = []
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.inspect", lambda self, credentials, client=None: _probe(None, None))
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", lambda self, credentials: [_position()])
    monkeypatch.setattr(
        "app.connectors.metaapi.MetaApiConnector.trade",
        lambda self, credentials, body: sent.append((credentials["token"], body)) or {"ok": True, "numeric_code": 10009, "string_code": "DONE", "message": "done", "order_id": "4", "position_id": "9001"},
    )
    saved = client.post(
        f"/api/v1/accounts/{account_id}/trading-api",
        headers=headers,
        json={"app_id": "account-id-1", "api_secret": "secret-value", "bot_token": "bot-token-value-123456"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["bot_token_set"] is True
    assert "secret-value" not in saved.text
    assert "bot-token-value-123456" not in saved.text
    closed = client.post("/api/v1/bot/close", headers={"Authorization": "Bearer bot-token-value-123456"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["closed_tickets"] == ["9001"]
    assert closed.json()["ai_trading_enabled"] is False
    assert sent[0][0] == "secret-value"
    assert sent[0][1]["actionType"] == "POSITION_CLOSE_ID"
    assert "secret-value" not in closed.text
    unknown = client.post("/api/v1/bot/close", headers={"Authorization": "Bearer not-the-saved-token"})
    assert unknown.status_code == 401

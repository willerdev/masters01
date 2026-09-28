import httpx
import pytest

from app.services.alert_service import TelegramError, send_bot_test

TOKEN = "123456789:AAHtesttokenvalueforthebot12345"


class _Client:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        payload = self.replies[method]
        return type("R", (), {"json": lambda self, payload=payload: payload})()


def _patch(monkeypatch, replies):
    client = _Client(replies)

    def factory(*args, **kwargs):
        return client

    monkeypatch.setattr(httpx, "Client", factory)
    return client


def test_send_bot_test_reaches_the_latest_chat(monkeypatch):
    client = _patch(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "guard_bot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": ""}},
            "getUpdates": {"ok": True, "result": [{"message": {"chat": {"id": 42}}}]},
            "sendMessage": {"ok": True, "result": {}},
        },
    )
    result = send_bot_test(TOKEN)
    assert result["sent"] is True
    assert result["bot"] == "guard_bot"
    assert ("sendMessage", {"chat_id": 42, "text": "TradeGuard test. This bot can reach you. Send a trade instruction in this chat."}) in client.calls
    assert TOKEN not in result["detail"]


def test_send_bot_test_pauses_a_webhook_and_restores_it(monkeypatch):
    client = _patch(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "guard_bot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": "https://example.test/hook"}},
            "deleteWebhook": {"ok": True, "result": True},
            "getUpdates": {"ok": True, "result": [{"message": {"chat": {"id": 7}}}]},
            "sendMessage": {"ok": True, "result": {}},
            "setWebhook": {"ok": True, "result": True},
        },
    )
    result = send_bot_test(TOKEN)
    methods = [call[0] for call in client.calls]
    assert methods == ["getMe", "getWebhookInfo", "deleteWebhook", "getUpdates", "sendMessage"]
    assert "setWebhook" not in methods
    assert result["chat_id"] == 7
    assert result["paused_webhook"] == ""


def test_send_bot_test_keeps_the_webhook_paused_until_a_chat_exists(monkeypatch):
    _patch(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "guard_bot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": "https://example.test/hook"}},
            "deleteWebhook": {"ok": True, "result": True},
            "getUpdates": {"ok": True, "result": []},
        },
    )
    result = send_bot_test(TOKEN)
    assert result["sent"] is False
    assert result["paused_webhook"] == "https://example.test/hook"
    assert "Send any message" in result["detail"]
    assert TOKEN not in result["detail"]


def test_send_bot_test_rejects_a_token_that_is_not_from_botfather():
    with pytest.raises(TelegramError) as caught:
        send_bot_test("not-a-telegram-token")
    assert "BotFather" in caught.value.detail

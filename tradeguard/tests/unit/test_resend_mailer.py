from app.services.email_service import resend_connected
from app.services.mailer import Mailer


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers, json):
        self.calls.append((url, headers, json))
        return self.response


def test_resend_sends_without_leaving_the_key_in_the_body(monkeypatch):
    client = _Client(_Response(200, {"id": "email_1"}))
    monkeypatch.setattr("app.services.mailer.httpx.Client", lambda timeout: client)
    mailer = Mailer()
    status = mailer.send(
        "ada@example.com",
        "Hello",
        "Body",
        api_key="re_secret_value",
        sender="TradeGuard <alerts@example.com>",
    )
    assert status == "sent"
    url, headers, body = client.calls[0]
    assert url == "https://api.resend.com/emails"
    assert headers["Authorization"] == "Bearer re_secret_value"
    assert body["from"] == "TradeGuard <alerts@example.com>"
    assert body["to"] == ["ada@example.com"]
    assert "re_secret_value" not in str(body)


def test_resend_reports_the_provider_message(monkeypatch):
    client = _Client(_Response(403, {"message": "The example.com domain is not verified."}))
    monkeypatch.setattr("app.services.mailer.httpx.Client", lambda timeout: client)
    mailer = Mailer()
    status = mailer.send("ada@example.com", "Hello", "Body", api_key="re_secret_value", sender="Desk <desk@example.com>")
    assert status == "failed"
    assert mailer.last_error == "The example.com domain is not verified."


def test_a_sending_only_resend_key_counts_as_connected(monkeypatch):
    class _Get:
        status_code = 401
        text = '{"message":"This API key is restricted to only send emails."}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers):
            return self

    monkeypatch.setattr("app.services.email_service.httpx.Client", lambda timeout: _Get())
    assert resend_connected("re_send_only") is True
    assert resend_connected("") is False

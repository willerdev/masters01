import sys
import time

from app.core.totp import totp_at


def _auth(client, email="setup@tradeguard.example"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _setup_body(code: str, password: str = "terminal-secret") -> dict:
    return {
        "country": "Kenya",
        "language": "en",
        "phone_country_code": "+254",
        "phone_number": "712345678",
        "admin_email": "setup@tradeguard.example",
        "totp_code": code,
        "account": {
            "connection_method": "local_mt5",
            "credentials": {"login": "440011", "password": password, "server": "Example-Live"},
        },
    }


def test_setup_stops_when_the_terminal_is_not_connected(client):
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    status = client.get("/api/v1/setup/status", headers=headers)
    assert status.status_code == 200, status.text
    code = totp_at(status.json()["mfa_secret"], int(time.time()))
    probe = client.post(
        "/api/v1/connections/probe",
        headers=headers,
        json={"connection_method": "local_mt5", "credentials": {"login": "440011", "password": "terminal-secret", "server": "Example-Live"}},
    )
    assert probe.status_code == 200, probe.text
    assert "terminal-secret" not in probe.text
    if not sys.platform.startswith("win"):
        assert probe.json()["ok"] is False
        assert probe.json()["error_code"] == "windows_terminal_required"
    done = client.post("/api/v1/setup/complete", headers=headers, json=_setup_body(code))
    assert done.status_code == 400, done.text
    assert "terminal-secret" not in done.text
    again = client.get("/api/v1/setup/status", headers=headers)
    assert again.json()["complete"] is False
    login = client.post("/api/v1/auth/login", json={"email": "setup@tradeguard.example", "password": "Sup3rSecret12"})
    assert login.status_code == 200, login.text
    assert login.json().get("access_token")


def test_setup_completes_after_a_live_connection(client, monkeypatch):
    def connected(method, credentials):
        assert credentials["password"] == "terminal-secret"
        return {
            "ok": True,
            "status": "connected",
            "error_code": "",
            "detail": "",
            "region": "",
            "account": {
                "display_name": "Desk MT5",
                "account_number": "440011",
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

    monkeypatch.setattr("app.services.account_service.probe_connection", connected)
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    status = client.get("/api/v1/setup/status", headers=headers)
    code = totp_at(status.json()["mfa_secret"], int(time.time()))
    done = client.post("/api/v1/setup/complete", headers=headers, json=_setup_body(code))
    assert done.status_code == 200, done.text
    assert done.json()["complete"] is True
    assert done.json()["account"]["account_number"] == "440011"
    assert done.json()["account"]["display_name"] == "Desk MT5"
    assert "terminal-secret" not in done.text
    login = client.post("/api/v1/auth/login", json={"email": "setup@tradeguard.example", "password": "Sup3rSecret12"})
    assert login.status_code == 200, login.text
    challenge = login.json()
    assert challenge["mfa_required"] is True
    assert "access_token" not in challenge
    wrong = "000000" if code != "000000" else "111111"
    rejected = client.post("/api/v1/auth/mfa", json={"mfa_token": challenge["mfa_token"], "code": wrong})
    assert rejected.status_code == 401
    accepted = client.post("/api/v1/auth/mfa", json={"mfa_token": challenge["mfa_token"], "code": code})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["access_token"]


def test_unknown_ai_provider_is_rejected(client):
    token = _auth(client, email="provider@tradeguard.example")
    response = client.put(
        "/api/v1/ai/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "deepseek", "model": "deepseek-chat", "enabled": False, "api_key": "sk-test"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "deepseek"
    assert response.json()["model"] == "deepseek-chat"
    assert "sk-test" not in response.text
    only_key = client.put(
        "/api/v1/ai/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "deepseek", "enabled": True, "api_key": "sk-only", "base_url": "not-a-host", "model": ""},
    )
    assert only_key.status_code == 200, only_key.text
    assert only_key.json()["model"] == "deepseek-chat"
    assert "not-a-host" not in only_key.text
    openai = client.put(
        "/api/v1/ai/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "openai", "enabled": True, "api_key": "sk-openai", "base_url": "https://evil.example/v1", "model": "gpt-hijack"},
    )
    assert openai.status_code == 200, openai.text
    assert openai.json()["provider"] == "deepseek"
    assert openai.json()["model"] == "deepseek-chat"
    assert "sk-openai" not in openai.text
    assert "evil.example" not in openai.text
    assert "gpt-hijack" not in openai.text
    rejected = client.put(
        "/api/v1/ai/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "unknown-vendor", "enabled": False},
    )
    assert rejected.status_code == 400

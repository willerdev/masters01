import json
from decimal import Decimal

import httpx

from app.connectors.payments import (
    canonical_status,
    cryptomus_signature,
    cryptomus_signature_matches,
    nowpayments_signature,
    nowpayments_signature_matches,
)
from app.core.totp import totp_at


def _auth(client, email="pay@tradeguard.example"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_status_mapping_never_treats_partial_payment_as_paid():
    assert canonical_status("nowpayments", "finished") == "paid"
    assert canonical_status("nowpayments", "partially_paid") == "underpaid"
    assert canonical_status("nowpayments", "waiting") == "waiting"
    assert canonical_status("nowpayments", "mystery") == "pending"
    assert canonical_status("cryptomus", "paid") == "paid"
    assert canonical_status("cryptomus", "paid_over") == "paid"
    assert canonical_status("cryptomus", "wrong_amount") == "underpaid"
    assert canonical_status("cryptomus", "check") == "waiting"


def test_signatures_reject_a_changed_body():
    body = {"order_id": "abc", "payment_status": "finished", "price_amount": "10.00"}
    secret = "ipn-secret-value"
    signature = nowpayments_signature(body, secret)
    assert nowpayments_signature_matches(body, secret, signature)
    assert nowpayments_signature_matches({**body, "payment_status": "waiting"}, secret, signature) is False
    crypto = {"amount": "10.00", "currency": "USD", "order_id": "abc"}
    sign = cryptomus_signature(crypto, "merchant-api-key")
    assert cryptomus_signature_matches({**crypto, "sign": sign}, "merchant-api-key", sign)
    assert cryptomus_signature_matches({**crypto, "amount": "11.00", "sign": sign}, "merchant-api-key", sign) is False


def test_provider_is_required_before_a_payment_request(client):
    token = _auth(client)
    missing = client.post(
        "/api/v1/payments",
        headers=_headers(token),
        json={"price_amount": "25.00", "price_currency": "USD", "purpose": "deposit"},
    )
    assert missing.status_code == 400
    assert "status" not in missing.json()
    unknown = client.put(
        "/api/v1/payments/provider",
        headers=_headers(token),
        json={"provider": "stripe", "credentials": {"api_key": "not-used"}},
    )
    assert unknown.status_code == 400


def test_nowpayments_request_stays_unpaid_until_a_signed_notification(client, monkeypatch):
    def probe(self, credentials, *, sandbox, client=None):
        assert credentials["api_key"] == "now-key-123456"
        assert sandbox is True
        return {"ok": True, "detail": "ok"}

    def create(self, credentials, **kwargs):
        assert kwargs["price_amount"] == Decimal("25.00")
        assert kwargs["callback_url"].startswith("http")
        return {
            "provider_payment_id": "pay_99",
            "invoice_url": "",
            "pay_address": "bc1qexample",
            "pay_amount": "0.001",
            "pay_currency": "btc",
            "provider_status": "waiting",
        }

    monkeypatch.setattr("app.connectors.payments.NowPaymentsConnector.probe", probe)
    monkeypatch.setattr("app.connectors.payments.NowPaymentsConnector.create_payment", create)
    token = _auth(client, email="now@tradeguard.example")
    headers = _headers(token)
    saved = client.put(
        "/api/v1/payments/provider",
        headers=headers,
        json={
            "provider": "nowpayments",
            "sandbox": True,
            "credentials": {
                "api_key": "now-key-123456",
                "api_url": "https://api-sandbox.nowpayments.io/v1",
                "ipn_secret": "ipn-secret-value",
                "payout_email": "payout@tradeguard.example",
                "payout_password": "payout-secret",
            },
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["provider"] == "nowpayments"
    assert "now-key-123456" not in saved.text
    assert "ipn-secret-value" not in saved.text
    assert "payout-secret" not in saved.text
    created = client.post(
        "/api/v1/payments",
        headers=headers,
        json={"price_amount": "25.00", "price_currency": "USD", "pay_currency": "btc", "purpose": "subscription"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "waiting"
    assert body["pay_address"] == "bc1qexample"
    assert body["ledger_posted"] is False
    me = client.get("/api/v1/auth/me", headers=headers).json()
    note = {"order_id": body["order_id"], "payment_status": "finished", "pay_address": "bc1qexample", "pay_amount": "0.001"}
    rejected = client.post(f"/api/v1/payments/ipn/nowpayments/{me['organization_id']}", json={**note, "payment_status": "finished"}, headers={"x-nowpayments-sig": "deadbeef"})
    assert rejected.status_code == 401
    listed = client.get("/api/v1/payments", headers=headers)
    assert listed.json()[0]["status"] == "waiting"
    signature = nowpayments_signature(note, "ipn-secret-value")
    accepted = client.post(
        f"/api/v1/payments/ipn/nowpayments/{me['organization_id']}",
        json=note,
        headers={"x-nowpayments-sig": signature},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "paid"
    partial = {**note, "payment_status": "partially_paid"}
    client.post(
        f"/api/v1/payments/ipn/nowpayments/{me['organization_id']}",
        json=partial,
        headers={"x-nowpayments-sig": nowpayments_signature(partial, "ipn-secret-value")},
    )
    again = client.get("/api/v1/payments", headers=headers)
    assert again.json()[0]["status"] == "underpaid"


def test_cryptomus_notification_uses_the_merchant_signature(client, monkeypatch):
    monkeypatch.setattr(
        "app.connectors.payments.CryptomusConnector.probe",
        lambda self, credentials, sandbox=False, client=None: {"ok": True, "detail": "ok"},
    )
    monkeypatch.setattr(
        "app.connectors.payments.CryptomusConnector.create_payment",
        lambda self, credentials, **kwargs: {
            "provider_payment_id": "uuid-1",
            "invoice_url": "https://pay.cryptomus.com/pay/uuid-1",
            "pay_address": "",
            "pay_amount": None,
            "pay_currency": "",
            "provider_status": "check",
        },
    )
    token = _auth(client, email="crypto@tradeguard.example")
    headers = _headers(token)
    saved = client.put(
        "/api/v1/payments/provider",
        headers=headers,
        json={"provider": "cryptomus", "credentials": {"merchant_id": "merchant-1234", "api_key": "merchant-api-key"}},
    )
    assert saved.status_code == 200, saved.text
    assert "merchant-api-key" not in saved.text
    created = client.post("/api/v1/payments", headers=headers, json={"price_amount": "10.00", "price_currency": "USD", "purpose": "deposit"})
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "waiting"
    assert created.json()["invoice_url"].startswith("https://pay.cryptomus.com/")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    note = {"order_id": created.json()["order_id"], "status": "paid", "uuid": "uuid-1"}
    note["sign"] = cryptomus_signature(note, "merchant-api-key")
    accepted = client.post(f"/api/v1/payments/ipn/cryptomus/{me['organization_id']}", json=note)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "paid"


def test_setup_does_not_finish_when_the_payment_provider_rejects_the_key(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.account_service.probe_connection",
        lambda method, credentials: {
            "ok": True,
            "status": "connected",
            "error_code": "",
            "detail": "",
            "region": "",
            "account": {
                "display_name": "Desk",
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
        },
    )
    monkeypatch.setattr(
        "app.connectors.payments.NowPaymentsConnector.probe",
        lambda self, credentials, sandbox=False, client=None: {"ok": False, "detail": "NOWPayments rejected the API key"},
    )
    token = _auth(client, email="setup-pay@tradeguard.example")
    headers = _headers(token)
    status = client.get("/api/v1/setup/status", headers=headers)
    import time

    code = totp_at(status.json()["mfa_secret"], int(time.time()))
    done = client.post(
        "/api/v1/setup/complete",
        headers=headers,
        json={
            "country": "Kenya",
            "language": "en",
            "phone_country_code": "+254",
            "phone_number": "712345678",
            "admin_email": "setup-pay@tradeguard.example",
            "totp_code": code,
            "account": {"connection_method": "local_mt5", "credentials": {"login": "440011", "password": "terminal-secret", "server": "Example-Live"}},
            "payment": {
                "provider": "nowpayments",
                "credentials": {
                    "api_key": "bad-key-value",
                    "api_url": "https://api.nowpayments.io/v1",
                    "ipn_secret": "bad-ipn-value",
                    "payout_email": "payout@tradeguard.example",
                    "payout_password": "bad-payout-password",
                },
            },
        },
    )
    assert done.status_code == 400, done.text
    assert "bad-key-value" not in done.text
    assert "bad-payout-password" not in done.text
    again = client.get("/api/v1/setup/status", headers=headers)
    assert again.json()["complete"] is False
    assert again.json()["mfa_enabled"] is False


def test_nowpayments_probe_checks_the_api_key_and_payout_login():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/merchant/coins"):
            assert request.headers.get("x-api-key") == "now-key-123456"
            return httpx.Response(200, json={"selectedCurrencies": []})
        assert request.url.path.endswith("/auth")
        body = json.loads(request.content.decode())
        assert body["email"] == "payout@tradeguard.example"
        assert body["password"] == "payout-secret"
        return httpx.Response(200, json={"token": "jwt-token-value"})

    from app.connectors.payments import NowPaymentsConnector

    credentials = {
        "api_key": "now-key-123456",
        "api_url": "https://api.nowpayments.io/v1",
        "ipn_secret": "ipn-secret-value",
        "payout_email": "payout@tradeguard.example",
        "payout_password": "payout-secret",
    }
    result = NowPaymentsConnector().probe(credentials, sandbox=False, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result["ok"] is True
    assert "jwt-token-value" not in result["detail"]
    assert "payout-secret" not in result["detail"]

    def rejected(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return httpx.Response(401, json={"message": "Invalid credentials"})
        return httpx.Response(200, json={"selectedCurrencies": []})

    failed = NowPaymentsConnector().probe(credentials, sandbox=False, client=httpx.Client(transport=httpx.MockTransport(rejected)))
    assert failed["ok"] is False
    assert "payout-secret" not in failed["detail"]
    missing = NowPaymentsConnector().probe({"api_key": "now-key-123456", "ipn_secret": "ipn-secret-value"}, sandbox=False)
    assert missing["ok"] is False
    assert "payout email" in missing["detail"]
    assert "401" in failed["detail"]
    assert "Invalid credentials" in failed["detail"]

    def bare_host(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/auth" or request.url.path == "/v1/merchant/coins"
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"token": "jwt-token-value"})
        return httpx.Response(200, json={"selectedCurrencies": []})

    bare = dict(credentials)
    bare["api_url"] = "https://api.nowpayments.io"
    reached = NowPaymentsConnector().probe(bare, sandbox=False, client=httpx.Client(transport=httpx.MockTransport(bare_host)))
    assert reached["ok"] is True

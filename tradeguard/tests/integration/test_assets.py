import json
from decimal import Decimal

import httpx

from app.connectors.payments import NowPaymentsConnector, nowpayments_signature


def _auth(client, email="asset-admin@tradeguard.example", organization="Asset Desk"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": organization},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _connect(client, headers):
    def probe(self, credentials, *, sandbox, client=None):
        return {"ok": True, "detail": "ok"}

    def create(self, credentials, **kwargs):
        return {
            "provider_payment_id": "pay_asset",
            "invoice_url": "https://nowpayments.io/invoice/asset",
            "pay_address": "bc1qassetdepositaddress000000000000",
            "pay_amount": str(kwargs["price_amount"]),
            "pay_currency": kwargs["pay_currency"],
            "provider_status": "waiting",
        }

    def payout(self, credentials, **kwargs):
        assert kwargs["address"].startswith("T")
        return {"provider_id": "wd_asset", "batch_id": "batch_asset", "provider_status": "WAITING"}

    client.app  # keep the fixture referenced
    return probe, create, payout


def _save_provider(client, monkeypatch, headers):
    probe, create, payout = _connect(client, headers)
    monkeypatch.setattr("app.connectors.payments.NowPaymentsConnector.probe", probe)
    monkeypatch.setattr("app.connectors.payments.NowPaymentsConnector.create_payment", create)
    monkeypatch.setattr("app.connectors.payments.NowPaymentsConnector.create_payout", payout)
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


def _investor_answers():
    return {
        "applicant_type": "individual",
        "country": "Rwanda",
        "tax_residency": "Rwanda",
        "date_of_birth": "1990-01-02",
        "category": "professional",
        "source_of_funds": "business",
        "expected_amount": "10000",
        "horizon": "over_3y",
        "objective": "growth",
        "experience": "some",
        "pep": "no",
        "phone": "+250700000000",
        "address": "Kigali",
        "id_type": "passport",
        "id_last4": "AB12",
        "risk_accepted": True,
    }


def test_nowpayments_payout_sends_the_login_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"token": "jwt-token"})
        assert request.headers["authorization"] == "Bearer jwt-token"
        body = json.loads(request.content)
        assert body["withdrawals"][0]["currency"] == "usdttrc20"
        assert body["withdrawals"][0]["amount"] == "25"
        return httpx.Response(200, json={"id": "batch1", "withdrawals": [{"id": "wd1", "status": "WAITING"}]})

    result = NowPaymentsConnector().create_payout(
        {"api_key": "now-key-123456", "api_url": "https://api.nowpayments.io/v1", "payout_email": "payout@tradeguard.example", "payout_password": "payout-secret"},
        sandbox=False,
        address="TYh6P7x1k8mN3qR5sV7wY9zA2bC4dE6fG8",
        currency="usdttrc20",
        amount=Decimal("25"),
        callback_url="https://desk.example/api/v1/payments/ipn/nowpayments/org",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result["provider_id"] == "wd1"
    assert result["provider_status"] == "WAITING"


def test_deposit_credits_only_after_nowpayments_confirms_and_withdraw_cannot_exceed_it(client, monkeypatch):
    admin = _auth(client)
    headers = _headers(admin)
    _save_provider(client, monkeypatch, headers)
    code = client.get("/api/v1/join-code", headers=headers).json()["code"]
    joined = client.post(
        "/api/v1/join",
        json={
            "code": code,
            "email": "asset-investor@tradeguard.example",
            "password": "Sup3rSecret12",
            "full_name": "Ada Investor",
            "kind": "investor",
            "answers": _investor_answers(),
        },
    )
    assert joined.status_code == 200, joined.text
    investor = joined.json()["access_token"]
    application_id = client.get("/api/v1/applications", headers=headers).json()["applications"][0]["id"]
    assert client.post(f"/api/v1/applications/{application_id}", headers=headers, json={"decision": "approve", "note": ""}).status_code == 200
    assert client.get("/api/v1/assets", headers=_headers(investor)).status_code == 200
    admin_deposit = client.post("/api/v1/assets/deposits", headers=headers, json={"currency": "usdttrc20", "amount": "10"})
    assert admin_deposit.status_code == 200, admin_deposit.text
    created = client.post("/api/v1/assets/deposits", headers=_headers(investor), json={"currency": "btc", "amount": "0.001"})
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "pending"
    assert created.json()["address"] == "bc1qassetdepositaddress000000000000"
    home = client.get("/api/v1/assets", headers=_headers(investor)).json()
    assert home["balances"] == []
    me = client.get("/api/v1/auth/me", headers=headers).json()
    note = {"order_id": client.get("/api/v1/payments", headers=headers).json()[0]["order_id"], "payment_status": "finished", "pay_amount": "0.001", "pay_currency": "btc"}
    signed = client.post(
        f"/api/v1/payments/ipn/nowpayments/{me['organization_id']}",
        json=note,
        headers={"x-nowpayments-sig": nowpayments_signature(note, "ipn-secret-value")},
    )
    assert signed.status_code == 200, signed.text
    home = client.get("/api/v1/assets", headers=_headers(investor)).json()
    assert Decimal(home["balances"][0]["available"]) == Decimal("0.001")
    admin_home = client.get("/api/v1/assets", headers=headers).json()
    assert admin_home["balances"] == []
    too_much = client.post(
        "/api/v1/assets/withdrawals",
        headers=_headers(investor),
        json={"currency": "btc", "amount": "1", "address": "TYh6P7x1k8mN3qR5sV7wY9zA2bC4dE6fG8"},
    )
    assert too_much.status_code == 400
    withdrawn = client.post(
        "/api/v1/assets/withdrawals",
        headers=_headers(investor),
        json={"currency": "btc", "amount": "0.0004", "address": "TYh6P7x1k8mN3qR5sV7wY9zA2bC4dE6fG8"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "pending"
    home = client.get("/api/v1/assets", headers=_headers(investor)).json()
    assert Decimal(home["balances"][0]["available"]) == Decimal("0.0006")
    payout = {"id": "wd_asset", "status": "FINISHED"}
    done = client.post(
        f"/api/v1/payments/ipn/nowpayments/{me['organization_id']}",
        json=payout,
        headers={"x-nowpayments-sig": nowpayments_signature(payout, "ipn-secret-value")},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "posted"

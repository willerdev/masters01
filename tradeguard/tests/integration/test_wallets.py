from decimal import Decimal


def _auth(client, email="wallet-admin@tradeguard.example"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Wallet Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


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


def test_wallet_cash_does_not_change_broker_equity_or_units(client, monkeypatch):
    token = _auth(client)
    headers = _headers(token)
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    account_id = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    ).json()["id"]
    fund_id = client.post("/api/v1/funds", headers=headers, json={"name": "Cash fund", "base_currency": "USD"}).json()["id"]
    assert client.post(f"/api/v1/funds/{fund_id}/accounts", headers=headers, json={"account_id": account_id}).status_code == 200
    assert client.post(f"/api/v1/funds/{fund_id}/nav", headers=headers).status_code == 200
    saved = client.post(
        f"/api/v1/funds/{fund_id}/wallets",
        headers=headers,
        json={"label": "Treasury", "address": "TYh6P7x1k8mN3qR5sV7wY9zA2bC4dE6fG8"},
    )
    assert saved.status_code == 200, saved.text
    wallet_id = saved.json()["id"]
    deposited = client.post(
        f"/api/v1/funds/{fund_id}/wallets/{wallet_id}/moves",
        headers=headers,
        json={"direction": "deposit", "amount": "500"},
    )
    assert deposited.status_code == 200, deposited.text
    assert deposited.json()["status"] == "posted"
    too_much = client.post(
        f"/api/v1/funds/{fund_id}/wallets/{wallet_id}/moves",
        headers=headers,
        json={"direction": "withdraw", "amount": "600"},
    )
    assert too_much.status_code == 400
    withdrawn = client.post(
        f"/api/v1/funds/{fund_id}/wallets/{wallet_id}/moves",
        headers=headers,
        json={"direction": "withdraw", "amount": "200"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    detail = client.get(f"/api/v1/funds/{fund_id}", headers=headers).json()
    assert Decimal(detail["snapshot"]["aum"]) == Decimal("10000")
    assert Decimal(detail["snapshot"]["units_outstanding"]) == Decimal("0")
    wallet = next(row for row in detail["wallets"] if row["id"] == wallet_id)
    assert Decimal(wallet["available"]) == Decimal("300")


def test_investor_can_withdraw_only_posted_wallet_cash(client):
    admin = _auth(client, "wallet-portal@tradeguard.example")
    headers = _headers(admin)
    code = client.get("/api/v1/join-code", headers=headers).json()["code"]
    joined = client.post(
        "/api/v1/join",
        json={
            "code": code,
            "email": "cash-investor@tradeguard.example",
            "password": "Sup3rSecret12",
            "full_name": "Ada Investor",
            "kind": "investor",
            "answers": {
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
            },
        },
    )
    assert joined.status_code == 200, joined.text
    investor_token = joined.json()["access_token"]
    application_id = client.get("/api/v1/applications", headers=headers).json()["applications"][0]["id"]
    assert client.post(f"/api/v1/applications/{application_id}", headers=headers, json={"decision": "approve", "note": ""}).status_code == 200
    fund_id = client.post("/api/v1/funds", headers=headers, json={"name": "Investor cash", "base_currency": "USD"}).json()["id"]
    saved = client.post(
        "/api/v1/portal/investor/wallets",
        headers=_headers(investor_token),
        json={"fund_id": fund_id, "label": "Mine", "address": "0x1234567890abcdef1234567890abcdef12345678"},
    )
    assert saved.status_code == 200, saved.text
    wallet_id = saved.json()["id"]
    blocked = client.post(
        f"/api/v1/portal/investor/wallets/{wallet_id}/moves",
        headers=_headers(investor_token),
        json={"direction": "withdraw", "amount": "10"},
    )
    assert blocked.status_code == 400
    requested = client.post(
        f"/api/v1/portal/investor/wallets/{wallet_id}/moves",
        headers=_headers(investor_token),
        json={"direction": "deposit", "amount": "250"},
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["status"] == "pending"
    portal = client.get("/api/v1/portal/investor", headers=_headers(investor_token)).json()
    assert Decimal(next(row for row in portal["wallets"] if row["id"] == wallet_id)["available"]) == Decimal("0")
    posted = client.post(
        f"/api/v1/funds/{fund_id}/wallet-moves/{requested.json()['id']}",
        headers=headers,
        json={"decision": "post"},
    )
    assert posted.status_code == 200, posted.text
    portal = client.get("/api/v1/portal/investor", headers=_headers(investor_token)).json()
    assert Decimal(next(row for row in portal["wallets"] if row["id"] == wallet_id)["available"]) == Decimal("250")
    withdrawn = client.post(
        f"/api/v1/portal/investor/wallets/{wallet_id}/moves",
        headers=_headers(investor_token),
        json={"direction": "withdraw", "amount": "80"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    portal = client.get("/api/v1/portal/investor", headers=_headers(investor_token)).json()
    assert Decimal(next(row for row in portal["wallets"] if row["id"] == wallet_id)["available"]) == Decimal("170")

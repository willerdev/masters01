from decimal import Decimal


def _auth(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "portal-admin@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Portal Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _investor_answers():
    return {
        "applicant_type": "individual",
        "country": "Rwanda",
        "tax_residency": "Rwanda",
        "date_of_birth": "1990-01-02",
        "category": "retail",
        "source_of_funds": "business",
        "expected_amount": "10000",
        "horizon": "1_to_3y",
        "objective": "growth",
        "experience": "some",
        "pep": "yes",
        "phone": "+250700000000",
        "address": "Kigali",
        "id_type": "passport",
        "id_last4": "AB12",
        "risk_accepted": True,
    }


def test_an_applicant_stays_out_until_the_admin_approves(client, monkeypatch):
    admin = _auth(client)
    headers = _headers(admin)
    code = client.get("/api/v1/join-code", headers=headers).json()["code"]
    joined = client.post(
        "/api/v1/join",
        json={
            "code": code,
            "email": "investor@tradeguard.example",
            "password": "Sup3rSecret12",
            "full_name": "Ada Investor",
            "kind": "investor",
            "answers": _investor_answers(),
        },
    )
    assert joined.status_code == 200, joined.text
    token = joined.json()["access_token"]
    assert joined.json()["user"]["roles"] == ["APPLICANT"]
    assert client.get("/api/v1/funds", headers=_headers(token)).status_code == 403
    home = client.get("/api/v1/portal/home", headers=_headers(token)).json()
    assert home["destination"] == "pending"
    queue = client.get("/api/v1/applications", headers=headers).json()
    application = queue["applications"][0]
    assert "Politically exposed" in application["flags"]
    assert "Retail investor" in application["flags"]
    approved = client.post(f"/api/v1/applications/{application['id']}", headers=headers, json={"decision": "approve", "note": "Welcome"})
    assert approved.status_code == 200, approved.text
    assert client.get("/api/v1/portal/home", headers=_headers(token)).json()["destination"] == "investor"
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
    account_id = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    ).json()["id"]
    fund_id = client.post("/api/v1/funds", headers=headers, json={"name": "Portal fund", "base_currency": "USD"}).json()["id"]
    assert client.post(f"/api/v1/funds/{fund_id}/accounts", headers=headers, json={"account_id": account_id}).status_code == 200
    assert client.post(f"/api/v1/funds/{fund_id}/nav", headers=headers).status_code == 200
    requested = client.post(
        "/api/v1/portal/investor/requests",
        headers=_headers(token),
        json={"fund_id": fund_id, "kind": "subscribe", "amount": "1000"},
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["status"] == "pending"
    decided = client.post(f"/api/v1/capital-requests/{requested.json()['id']}", headers=headers, json={"decision": "approve", "note": ""})
    assert decided.status_code == 200, decided.text
    portal = client.get("/api/v1/portal/investor", headers=_headers(token)).json()
    holding = next(row for row in portal["funds"] if row["id"] == fund_id)
    assert Decimal(holding["units"]) == Decimal("1000")

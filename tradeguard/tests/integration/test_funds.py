from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.connectors.types import NormalizedPosition, NormalizedQuote


def _auth(client, email="fund@tradeguard.example"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Fund Desk"},
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


def test_nav_follows_live_equity_and_subscriptions_do_not_change_it(client, monkeypatch):
    token = _auth(client)
    headers = _headers(token)
    account_id = _account(client, monkeypatch, headers)
    created = client.post(
        "/api/v1/funds",
        headers=headers,
        json={"name": "Main fund", "base_currency": "USD", "management_fee_pct": "0", "performance_fee_pct": "20"},
    )
    assert created.status_code == 200, created.text
    fund_id = created.json()["id"]
    attached = client.post(f"/api/v1/funds/{fund_id}/accounts", headers=headers, json={"account_id": account_id})
    assert attached.status_code == 200, attached.text
    published = client.post(f"/api/v1/funds/{fund_id}/nav", headers=headers)
    assert published.status_code == 200, published.text
    assert Decimal(published.json()["aum"]) == Decimal("10000")
    assert Decimal(published.json()["unit_price"]) == Decimal("1")
    assert published.json()["locked"] is True
    subscribed = client.post(
        f"/api/v1/funds/{fund_id}/subscriptions",
        headers=headers,
        json={"name": "Ada Investor", "email": "ada.investor@tradeguard.example", "amount": "10000"},
    )
    assert subscribed.status_code == 200, subscribed.text
    assert Decimal(subscribed.json()["units"]) == Decimal("10000")
    from app.core.database import SessionLocal
    from app.models.entities import AccountState

    db = SessionLocal()
    try:
        state = db.get(AccountState, UUID(account_id))
        assert state.equity == Decimal("10000")
        state.equity = Decimal("11000")
        db.commit()
    finally:
        db.close()
    again = client.post(f"/api/v1/funds/{fund_id}/nav", headers=headers)
    assert again.status_code == 200, again.text
    assert Decimal(again.json()["aum"]) == Decimal("11000")
    assert Decimal(again.json()["unit_price"]) == Decimal("1.1")
    fees = client.post(f"/api/v1/funds/{fund_id}/fees", headers=headers)
    assert fees.status_code == 200, fees.text
    assert fees.json()[0]["kind"] == "performance"
    assert Decimal(fees.json()[0]["amount"]) == Decimal("200")
    detail = client.get(f"/api/v1/funds/{fund_id}", headers=headers).json()
    investor_id = detail["investors"][0]["id"]
    too_much = client.post(f"/api/v1/funds/{fund_id}/redemptions", headers=headers, json={"investor_id": investor_id, "amount": "999999"})
    assert too_much.status_code == 400


def test_a_fund_guideline_blocks_the_order(client, monkeypatch):
    token = _auth(client, email="guide@tradeguard.example")
    headers = _headers(token)
    account_id = _account(client, monkeypatch, headers)
    fund_id = client.post("/api/v1/funds", headers=headers, json={"name": "Guide fund", "base_currency": "USD"}).json()["id"]
    assert client.post(f"/api/v1/funds/{fund_id}/accounts", headers=headers, json={"account_id": account_id}).status_code == 200
    from app.core.database import SessionLocal
    from app.models.entities import Position

    db = SessionLocal()
    try:
        db.add(
            Position(
                account_id=UUID(account_id),
                ticket="fund-1",
                symbol="EURUSD",
                side="buy",
                volume=Decimal("1"),
                entry_price=Decimal("5000"),
                current_price=Decimal("5000"),
                status="open",
            )
        )
        db.commit()
    finally:
        db.close()
    saved = client.post(
        f"/api/v1/funds/{fund_id}/guidelines",
        headers=headers,
        json={"name": "Symbol weight", "metric": "symbol_weight_pct", "operator": ">", "threshold": "10", "action": "block"},
    )
    assert saved.status_code == 200, saved.text
    sent = []
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_quote", _quote)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_symbol_spec", lambda self, credentials, symbol: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.trade", lambda self, credentials, body: sent.append(body))
    response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        headers=headers,
        json={"action": "open", "symbol": "EURUSD", "side": "buy", "volume": "0.10"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sent"] is False
    assert response.json()["decision"] == "BLOCK"
    assert any(hit["code"] == "FUND_GUIDELINE" for hit in response.json()["hits"])
    assert sent == []


def test_reconcile_reports_a_broker_break(client, monkeypatch):
    token = _auth(client, email="recon@tradeguard.example")
    headers = _headers(token)
    account_id = _account(client, monkeypatch, headers)
    fund_id = client.post("/api/v1/funds", headers=headers, json={"name": "Recon fund", "base_currency": "USD"}).json()["id"]
    client.post(f"/api/v1/funds/{fund_id}/accounts", headers=headers, json={"account_id": account_id})
    monkeypatch.setattr(
        "app.connectors.metaapi.MetaApiConnector.fetch_positions",
        lambda self, credentials: [NormalizedPosition(None, "remote-1", "EURUSD", "buy", Decimal("0.1"), Decimal("1"), Decimal("1"), None, None, Decimal("0"), Decimal("0"), Decimal("0"), None, None, "")],
    )
    rows = client.post(f"/api/v1/funds/{fund_id}/reconcile", headers=headers)
    assert rows.status_code == 200, rows.text
    assert rows.json()[0]["status"] == "break"
    assert rows.json()[0]["detail"]["missing_locally"] == ["remote-1"]

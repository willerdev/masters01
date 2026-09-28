from decimal import Decimal

from app.connectors.normalize import normalize_position
from app.connectors.types import NormalizedAccount


def _auth(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "book@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _probe(method, credentials):
    assert credentials["token"] == "metaapi-token-value"
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


def _position(ticket: str) -> object:
    return normalize_position(
        {
            "ticket": ticket,
            "symbol": "EURUSD",
            "side": "buy",
            "volume": "0.10",
            "entry_price": "1.10000",
            "current_price": "1.10100",
            "profit": "10",
            "magic_number": 51001,
        }
    )


def test_open_trades_come_from_the_connected_terminal(client, monkeypatch):
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    webhook = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"display_name": "Webhook", "account_number": "1", "connection_method": "webhook"},
    )
    assert webhook.status_code == 200, webhook.text
    live = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert live.status_code == 200, live.text
    books = [[_position("9001")], []]

    def fetch(self, credentials):
        assert credentials["token"] == "metaapi-token-value"
        return books.pop(0)

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", fetch)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_account", lambda self, credentials: None)
    first = client.get("/api/v1/trades", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["trades"]) == 1
    assert body["trades"][0]["symbol"] == "EURUSD"
    assert body["trades"][0]["account_name"] == "Live book"
    assert body["trades"][0]["ticket"] == "9001"
    assert "metaapi-token-value" not in first.text
    second = client.get("/api/v1/trades", headers=headers)
    assert second.json()["trades"] == []


def test_a_failed_terminal_read_keeps_the_last_open_trades(client, monkeypatch):
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    calls = {"n": 0}

    def fetch(self, credentials):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_position("9002")]
        raise RuntimeError("terminal timeout")

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", fetch)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_account", lambda self, credentials: None)
    first = client.get("/api/v1/trades", headers=headers)
    assert first.json()["trades"][0]["ticket"] == "9002"
    second = client.get("/api/v1/trades", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["trades"][0]["ticket"] == "9002"
    assert second.json()["errors"][0]["detail"] == "terminal timeout"


def test_account_page_sync_refreshes_price_and_equity(client, monkeypatch):
    monkeypatch.setattr("app.services.account_service.probe_connection", _probe)
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"connection_method": "metaapi", "credentials": {"token": "metaapi-token-value", "metaapi_account_id": "account-id-1"}},
    )
    assert created.status_code == 200, created.text
    account_id = created.json()["id"]
    quotes = iter(["1.10100", "1.10420"])
    profits = iter(["10", "42.5"])
    equities = iter(["10000", "10032.50"])

    def fetch(self, credentials):
        return [
            normalize_position(
                {
                    "ticket": "9003",
                    "symbol": "EURUSD",
                    "side": "buy",
                    "volume": "0.10",
                    "entry_price": "1.10000",
                    "current_price": next(quotes),
                    "profit": next(profits),
                }
            )
        ]

    def account(self, credentials):
        equity = next(equities)
        return NormalizedAccount(
            balance=Decimal("10000"),
            equity=Decimal(equity),
            margin=Decimal("20"),
            free_margin=Decimal("9980"),
            margin_level=Decimal("50000"),
            currency="USD",
        )

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_positions", fetch)
    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_account", account)
    first = client.get(f"/api/v1/accounts/{account_id}?sync=1", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["equity"] == "10000.00"
    assert first.json()["positions"][0]["current_price"] == "1.101"
    assert first.json()["positions"][0]["floating_pl"] == "10.00"
    second = client.get(f"/api/v1/accounts/{account_id}?sync=1", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["equity"] == "10032.50"
    assert second.json()["positions"][0]["current_price"] == "1.1042"
    assert second.json()["positions"][0]["floating_pl"] == "42.50"

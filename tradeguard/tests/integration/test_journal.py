def _auth(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "journal@tradeguard.example", "password": "Sup3rSecret12", "full_name": "Ada", "organization_name": "Desk"},
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
            "equity": "10040",
            "margin": "0",
            "free_margin": "10000",
            "margin_level": None,
        },
    }


def test_journal_splits_days_and_dashboard_has_a_curve(client, monkeypatch):
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

    def deals(self, credentials, start, end):
        return [
            {"id": "d1", "type": "DEAL_TYPE_BUY", "symbol": "EURUSD", "volume": "0.1", "price": "1.1", "profit": "25", "time": "2026-09-20T10:00:00.000Z"},
            {"id": "d2", "type": "DEAL_TYPE_SELL", "symbol": "USDJPY", "volume": "0.2", "price": "150", "profit": "-15", "time": "2026-09-21T10:00:00.000Z"},
            {"id": "d3", "type": "DEAL_TYPE_BUY", "symbol": "GBPUSD", "volume": "0.1", "price": "1.3", "profit": "0", "time": "2026-09-22T10:00:00.000Z"},
            {"id": "bal", "type": "DEAL_TYPE_BALANCE", "profit": "100", "time": "2026-09-22T11:00:00.000Z"},
        ]

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_deals", deals)
    journal = client.get(f"/api/v1/journal?account_id={account_id}", headers=headers)
    assert journal.status_code == 200, journal.text
    body = journal.json()
    assert body["summary"]["profitable_days"] == 1
    assert body["summary"]["loss_days"] == 1
    assert body["summary"]["even_days"] == 1
    assert body["summary"]["net"] == "10.00"
    assert "metaapi-token-value" not in journal.text
    charts = client.get("/api/v1/dashboard/charts", headers=headers)
    assert charts.status_code == 200, charts.text
    assert charts.json()["equity"]
    assert any(point["equity"] == "10040.00" for point in charts.json()["equity"])
    assert charts.json()["daily_pnl"]


def test_a_closed_trade_keeps_the_opening_source(client, monkeypatch):
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

    def deals(self, credentials, start, end):
        return [
            {
                "id": "in1",
                "positionId": "p1",
                "type": "DEAL_TYPE_BUY",
                "entryType": "DEAL_ENTRY_IN",
                "symbol": "EURUSD",
                "volume": "0.1",
                "price": "1.1",
                "profit": "0",
                "comment": "Signals",
                "time": "2026-09-20T09:00:00.000Z",
            },
            {
                "id": "out1",
                "positionId": "p1",
                "type": "DEAL_TYPE_SELL",
                "entryType": "DEAL_ENTRY_OUT",
                "symbol": "EURUSD",
                "volume": "0.1",
                "price": "1.2",
                "profit": "40",
                "comment": "",
                "time": "2026-09-20T12:00:00.000Z",
            },
        ]

    monkeypatch.setattr("app.connectors.metaapi.MetaApiConnector.fetch_deals", deals)
    journal = client.get(f"/api/v1/journal?account_id={account_id}", headers=headers)
    assert journal.status_code == 200, journal.text
    body = journal.json()
    trades = [trade for day in body["days"] for trade in day["trades"]]
    assert [trade["ticket"] for trade in trades] == ["out1"]
    assert trades[0]["source"] == "Signals"
    assert body["sources"] == [{"source": "Signals", "net": "40.00", "trades": 1, "result": "profit"}]

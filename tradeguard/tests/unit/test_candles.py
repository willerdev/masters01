from app.connectors.metaapi import MetaApiConnector


def test_candles_come_from_the_market_data_host(monkeypatch):
    seen = {}

    def fake(self, method, url, token, client=None, json=None):
        seen["url"] = url

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {"time": "2026-09-26T21:45:00.000Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
                    {"time": "2026-09-26T21:30:00.000Z", "open": 1, "high": 1.2, "low": 0.8, "close": 1},
                ]

        return Response()

    monkeypatch.setattr(MetaApiConnector, "_request", fake)
    rows = MetaApiConnector().fetch_candles(
        {"token": "t", "metaapi_account_id": "account-id-1", "region": "london"},
        "Volatility 75 Index",
        "15m",
        limit=2,
    )
    assert "mt-market-data-client-api-v1.london" in seen["url"]
    assert "Volatility%2075%20Index" in seen["url"]
    assert [row["time"] for row in rows] == sorted(row["time"] for row in rows)
    assert rows[-1]["close"] == "1.5"

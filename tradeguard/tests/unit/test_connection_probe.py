import httpx

from app.connectors.metaapi import MetaApiConnector

_ACCOUNT = "1eda642a-a9a3-457c-99af-3bc5e8d5c4c9"


def _provision(**overrides):
    body = {
        "_id": _ACCOUNT,
        "login": "50194988",
        "name": "mt5a",
        "server": "ICMarketsSC-Demo",
        "state": "DEPLOYED",
        "connectionStatus": "CONNECTED",
        "region": "london",
        "baseCurrency": "USD",
    }
    body.update(overrides)
    return body


def test_metaapi_region_and_identity_come_from_the_token_lookup():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["auth-token"] == "secret-token"
        if "provisioning" in str(request.url):
            return httpx.Response(200, json=_provision())
        assert "mt-client-api-v1.london.agiliumtrade.ai" in str(request.url)
        return httpx.Response(
            200,
            json={
                "login": 50194988,
                "name": "mt5a",
                "server": "ICMarketsSC-Demo",
                "broker": "Raw Trading Ltd",
                "currency": "USD",
                "leverage": 500,
                "balance": 1000,
                "equity": 990,
                "margin": 0,
                "freeMargin": 990,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = MetaApiConnector().inspect(
            {"token": "secret-token", "metaapi_account_id": _ACCOUNT},
            client,
        )
    assert result["ok"] is True
    assert result["region"] == "london"
    assert result["account"]["account_number"] == "50194988"
    assert result["account"]["broker"] == "Raw Trading Ltd"
    assert result["account"]["leverage"] == "500"
    assert "secret-token" not in str(result)


def test_metaapi_disconnected_account_cannot_continue():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "provisioning" in str(request.url)
        return httpx.Response(200, json=_provision(connectionStatus="DISCONNECTED"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = MetaApiConnector().inspect({"token": "secret-token", "metaapi_account_id": _ACCOUNT}, client)
    assert result["ok"] is False
    assert result["error_code"] == "metaapi_not_connected"
    assert result["region"] == ""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx

from app.connectors.normalize import normalize_account, normalize_position, normalize_quote
from app.connectors.types import CloseResult, ConnectionTest, ConnectorCapabilities, NormalizedAccount, NormalizedPosition, NormalizedQuote
from app.core.config import get_settings
from app.core.resilience import CircuitBreaker, CircuitOpen

_breaker = CircuitBreaker(fail_max=4, reset_seconds=45)
_PROVISIONING = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
_REGION = re.compile(r"[a-z0-9-]{2,40}")
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mn"}
_DONE = {10008, 10009, 10010}


class MetaApiConnector:
    name = "metaapi"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(True, True, True, "metaapi")

    def _base(self, region: str | None) -> str:
        chosen = region or get_settings().metaapi_region
        return f"https://mt-client-api-v1.{chosen}.agiliumtrade.ai"

    def _market_base(self, region: str | None) -> str:
        chosen = region or get_settings().metaapi_region
        return f"https://mt-market-data-client-api-v1.{chosen}.agiliumtrade.ai"

    def _headers(self, token: str) -> dict[str, str]:
        return {"auth-token": token, "Accept": "application/json"}

    def _request(
        self,
        method: str,
        url: str,
        token: str,
        client: httpx.Client | None = None,
        json: dict | None = None,
    ) -> httpx.Response:
        def send() -> httpx.Response:
            kwargs: dict = {"headers": self._headers(token)}
            if json is not None:
                kwargs["json"] = json
            if client is None:
                with httpx.Client(timeout=12.0) as owned:
                    response = owned.request(method, url, **kwargs)
            else:
                response = client.request(method, url, **kwargs)
            if response.status_code >= 500:
                raise httpx.HTTPError(f"metaapi {response.status_code}")
            return response

        if client is not None:
            return send()
        return _breaker.call(send)

    def inspect(self, credentials: dict, client: httpx.Client | None = None) -> dict:
        token = str(credentials.get("token") or "").strip()
        account_id = str(credentials.get("metaapi_account_id") or "").strip()
        if not token or not account_id:
            return _probe_fail("missing_credentials", "credentials_missing", "Enter the MetaAPI token and account id")
        if not _ACCOUNT_ID.fullmatch(account_id):
            return _probe_fail("rejected", "metaapi_account_id", "Enter the MetaAPI account id")
        try:
            provision = self._request("GET", f"{_PROVISIONING}/users/current/accounts/{account_id}", token, client)
        except CircuitOpen:
            return _probe_fail("circuit_open", "metaapi_circuit_open", "MetaAPI circuit is open")
        except httpx.HTTPError:
            return _probe_fail("unreachable", "metaapi_unreachable", "MetaAPI request failed")
        if provision.status_code == 401:
            return _probe_fail("rejected", "metaapi_unauthorized", "MetaAPI rejected the token")
        if provision.status_code == 404:
            return _probe_fail("rejected", "metaapi_account_not_found", "MetaAPI did not find that account id")
        if provision.status_code != 200:
            return _probe_fail("rejected", f"http_{provision.status_code}", "MetaAPI account lookup failed")
        body = provision.json()
        region = str(body.get("region") or "").strip().lower()
        if not _REGION.fullmatch(region):
            return _probe_fail("rejected", "metaapi_region_missing", "MetaAPI did not return a region for this account")
        state = str(body.get("state") or "")
        connection = str(body.get("connectionStatus") or "")
        if state != "DEPLOYED":
            return _probe_fail("not_ready", "metaapi_not_deployed", f"MetaAPI account state is {state or 'unknown'}")
        if connection != "CONNECTED":
            return _probe_fail("disconnected", "metaapi_not_connected", "MetaAPI is not connected to the broker")
        info_url = f"{self._base(region)}/users/current/accounts/{account_id}/account-information"
        try:
            info = self._request("GET", info_url, token, client)
        except CircuitOpen:
            return _probe_fail("circuit_open", "metaapi_circuit_open", "MetaAPI circuit is open")
        except httpx.HTTPError:
            return _probe_fail("unreachable", "metaapi_unreachable", "MetaAPI account information request failed")
        if info.status_code != 200:
            return _probe_fail("rejected", f"http_{info.status_code}", "MetaAPI account information is not available")
        data = info.json()
        login = str(data.get("login") or body.get("login") or "").strip()
        name = str(data.get("name") or body.get("name") or login).strip()
        server = str(data.get("server") or body.get("server") or "").strip()
        broker = str(data.get("broker") or data.get("company") or "").strip()
        currency = str(data.get("currency") or body.get("baseCurrency") or "USD").strip() or "USD"
        leverage = data.get("leverage") or "100"
        return {
            "ok": True,
            "status": "connected",
            "error_code": "",
            "detail": "",
            "region": region,
            "account": {
                "display_name": name or login or "MetaAPI account",
                "account_number": login,
                "broker": broker,
                "server": server,
                "currency": currency.upper(),
                "leverage": str(leverage),
                "balance": str(data.get("balance") or "0"),
                "equity": str(data.get("equity") or "0"),
                "margin": str(data.get("margin") or "0"),
                "free_margin": str(data.get("freeMargin") or data.get("free_margin") or "0"),
                "margin_level": None if data.get("marginLevel") in (None, "") else str(data.get("marginLevel")),
            },
        }

    def test_connection(self, credentials: dict) -> ConnectionTest:
        result = self.inspect(credentials)
        return ConnectionTest(result["ok"], result["status"], result["error_code"], result["detail"])

    def fetch_account(self, credentials: dict) -> NormalizedAccount:
        token = str(credentials["token"])
        account_id = str(credentials["metaapi_account_id"])
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/account-information"
        response = self._request("GET", url, token)
        response.raise_for_status()
        return normalize_account(response.json())

    def fetch_orders(self, credentials: dict) -> list[dict]:
        token = str(credentials.get("token") or "")
        account_id = str(credentials.get("metaapi_account_id") or "")
        if not token or not account_id:
            raise ValueError("orders_unavailable")
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/orders"
        response = self._request("GET", url, token)
        response.raise_for_status()
        body = response.json()
        rows = body if isinstance(body, list) else body.get("orders", [])
        return [row for row in rows if isinstance(row, dict)]

    def fetch_positions(self, credentials: dict) -> list[NormalizedPosition]:
        token = str(credentials["token"])
        account_id = str(credentials["metaapi_account_id"])
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/positions"
        response = self._request("GET", url, token)
        response.raise_for_status()
        body = response.json()
        rows = body if isinstance(body, list) else body.get("positions", [])
        return [normalize_position(row, account_id) for row in rows]

    def fetch_deals(self, credentials: dict, start, end) -> list[dict]:
        from urllib.parse import quote

        token = str(credentials["token"])
        account_id = str(credentials["metaapi_account_id"])
        start_text = quote(start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), safe="")
        end_text = quote(end.strftime("%Y-%m-%dT%H:%M:%S.000Z"), safe="")
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/history-deals/time/{start_text}/{end_text}"
        response = self._request("GET", url, token)
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list):
            return body
        return list(body.get("deals") or [])

    def fetch_quote(self, credentials: dict, symbol: str) -> NormalizedQuote:
        token = str(credentials["token"])
        account_id = str(credentials["metaapi_account_id"])
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/symbols/{quote(symbol, safe='')}/current-price"
        response = self._request("GET", url, token)
        response.raise_for_status()
        payload = response.json()
        payload["symbol"] = symbol
        return normalize_quote(payload, source="metaapi")

    def close_all(self, credentials: dict) -> CloseResult:
        token = str(credentials.get("token") or "")
        account_id = str(credentials.get("metaapi_account_id") or "")
        if not token or not account_id:
            return CloseResult(False, "metaapi", error_code="credentials_missing")
        try:
            positions = self.fetch_positions(credentials)
        except Exception:  # noqa: BLE001
            return CloseResult(False, "metaapi", error_code="positions_unavailable")
        closed: list[str] = []
        for position in positions:
            url = (
                f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}"
                f"/positions/{position.ticket}"
            )
            try:
                response = self._request("DELETE", url, token)
            except Exception:  # noqa: BLE001
                return CloseResult(False, "metaapi", closed_tickets=closed, error_code="close_failed")
            if response.status_code in {200, 204}:
                closed.append(position.ticket)
        return CloseResult(True, "metaapi", closed_tickets=closed)

    def trade(self, credentials: dict, body: dict) -> dict:
        token = str(credentials.get("token") or "")
        account_id = str(credentials.get("metaapi_account_id") or "")
        if not token or not account_id:
            return _trade_fail("credentials_missing")
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/trade"
        try:
            response = self._request("POST", url, token, json=body)
        except CircuitOpen:
            return _trade_fail("metaapi_circuit_open")
        except httpx.HTTPError:
            return _trade_fail("metaapi_unreachable")
        return _trade_result(response)

    def fetch_candles(self, credentials: dict, symbol: str, timeframe: str, limit: int = 200) -> list[dict]:
        token = str(credentials.get("token") or "")
        account_id = str(credentials.get("metaapi_account_id") or "")
        if timeframe not in _TIMEFRAMES:
            raise ValueError("unsupported timeframe")
        if not token or not account_id or not symbol.strip():
            raise ValueError("candles_unavailable")
        safe_symbol = quote(symbol.strip(), safe="")
        url = (
            f"{self._market_base(credentials.get('region'))}/users/current/accounts/{account_id}"
            f"/historical-market-data/symbols/{safe_symbol}/timeframes/{timeframe}/candles?limit={limit}"
        )
        response = self._request("GET", url, token)
        response.raise_for_status()
        body = response.json()
        rows = body if isinstance(body, list) else body.get("candles", [])
        candles = []
        seen: set[int] = set()
        for row in rows:
            candle = _candle(row)
            if candle is None or candle["time"] in seen:
                continue
            seen.add(candle["time"])
            candles.append(candle)
        candles.sort(key=lambda item: item["time"])
        return candles

    def fetch_symbol_spec(self, credentials: dict, symbol: str) -> dict:
        token = str(credentials.get("token") or "")
        account_id = str(credentials.get("metaapi_account_id") or "")
        safe_symbol = quote(symbol.strip(), safe="")
        url = f"{self._base(credentials.get('region'))}/users/current/accounts/{account_id}/symbols/{safe_symbol}/specification"
        response = self._request("GET", url, token)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("symbol spec unavailable")
        return _spec_payload(body)


def _probe_fail(status: str, error_code: str, detail: str) -> dict:
    return {"ok": False, "status": status, "error_code": error_code, "detail": detail, "region": "", "account": None}


def _trade_fail(message: str) -> dict:
    return {"ok": False, "numeric_code": 0, "string_code": "", "message": message, "order_id": "", "position_id": ""}


def _trade_result(response: httpx.Response) -> dict:
    data: dict = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            data = parsed
    except ValueError:
        data = {}
    raw_code = data.get("numericCode")
    try:
        numeric = int(raw_code) if raw_code is not None else response.status_code
    except (TypeError, ValueError):
        numeric = response.status_code
    message = str(data.get("message") or data.get("stringCode") or "")[:240]
    confirmed = response.status_code < 300 and numeric in _DONE
    if response.status_code < 300 and raw_code is None:
        confirmed = False
        message = message or "MetaAPI did not confirm the order"
    if not message and not confirmed:
        message = "MetaAPI rejected the order"
    return {
        "ok": confirmed,
        "numeric_code": numeric,
        "string_code": str(data.get("stringCode") or "")[:80],
        "message": message,
        "order_id": str(data.get("orderId") or ""),
        "position_id": str(data.get("positionId") or ""),
    }


def _candle(row: object) -> dict | None:
    if not isinstance(row, dict) or "time" not in row:
        return None
    text = str(row["time"]).replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
        prices = [Decimal(str(row[name])) for name in ("open", "high", "low", "close")]
    except (InvalidOperation, KeyError, ValueError):
        return None
    return {
        "time": int(moment.timestamp()),
        "open": str(prices[0]),
        "high": str(prices[1]),
        "low": str(prices[2]),
        "close": str(prices[3]),
    }


def _dec(value: object, default: str) -> str:
    if value in (None, ""):
        return default
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return default


def _spec_payload(body: dict) -> dict:
    tick = _dec(body.get("tickSize") or body.get("point"), "0")
    contract = _dec(body.get("contractSize") or body.get("tradeContractSize"), "0")
    tick_value = body.get("tickValue")
    if tick_value in (None, ""):
        try:
            tick_value = str(Decimal(tick) * Decimal(contract))
        except InvalidOperation:
            tick_value = "0"
    return {
        "tick_size": tick,
        "tick_value": _dec(tick_value, "0"),
        "contract_size": contract,
        "volume_min": _dec(body.get("minVolume"), "0.01"),
        "volume_max": _dec(body.get("maxVolume"), "100"),
        "volume_step": _dec(body.get("volumeStep"), "0.01"),
        "profit_currency": str(body.get("profitCurrency") or "USD"),
        "digits": int(body.get("digits") or 5),
        "calc_mode": "forex",
        "asset_class": "forex",
    }

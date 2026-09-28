from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from urllib.parse import urlparse

import httpx

from app.core.resilience import CircuitBreaker, CircuitOpen

PROVIDERS = ("nowpayments", "cryptomus")
NOWPAYMENTS_LIVE = "https://api.nowpayments.io/v1"
NOWPAYMENTS_SANDBOX = "https://api-sandbox.nowpayments.io/v1"
CRYPTOMUS_LIVE = "https://api.cryptomus.com/v1"

_breakers = {
    "nowpayments": CircuitBreaker(fail_max=4, reset_seconds=45),
    "cryptomus": CircuitBreaker(fail_max=4, reset_seconds=45),
}


class PaymentProviderError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def canonical_status(provider: str, raw: str) -> str:
    """Map a provider status onto TradeGuard's payment states. Unknown values stay unpaid."""
    value = (raw or "").strip().lower()
    if provider == "nowpayments":
        if value == "finished":
            return "paid"
        if value in {"confirming", "confirmed", "sending"}:
            return "confirming"
        if value == "partially_paid":
            return "underpaid"
        if value == "expired":
            return "expired"
        if value in {"failed", "refunded"}:
            return "failed"
        if value == "waiting":
            return "waiting"
        return "pending"
    if provider == "cryptomus":
        if value in {"paid", "paid_over"}:
            return "paid"
        if value in {"wrong_amount", "wrong_amount_waiting"}:
            return "underpaid"
        if value in {"fail", "cancel", "system_fail", "refund_fail", "refund_paid"}:
            return "failed"
        if value in {"confirm_check", "process", "refund_process"}:
            return "confirming"
        if value in {"check", "wait"}:
            return "waiting"
        return "pending"
    return "pending"


def _sort(value: object) -> object:
    if isinstance(value, dict):
        return {key: _sort(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort(item) for item in value]
    return value


def nowpayments_signature(body: dict, ipn_secret: str) -> str:
    payload = json.dumps(_sort(body), separators=(",", ":"), ensure_ascii=False)
    return hmac.new(ipn_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha512).hexdigest()


def nowpayments_signature_matches(body: dict, ipn_secret: str, signature: str) -> bool:
    if not signature or not ipn_secret:
        return False
    expected = nowpayments_signature(body, ipn_secret)
    return hmac.compare_digest(expected, signature.strip())


def cryptomus_body(body: dict, api_key: str) -> tuple[str, str]:
    """JSON text and MD5 sign. The posted body must be this exact text."""
    encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).replace("/", "\\/")
    digest = base64.b64encode(encoded.encode("utf-8")).decode("ascii")
    sign = hashlib.md5((digest + api_key).encode("utf-8")).hexdigest()  # noqa: S324
    return encoded, sign


def cryptomus_signature(body: dict, api_key: str) -> str:
    return cryptomus_body(body, api_key)[1]


def cryptomus_signature_matches(body: dict, api_key: str, signature: str) -> bool:
    if not signature or not api_key:
        return False
    unsigned = {key: value for key, value in body.items() if key != "sign"}
    expected = cryptomus_signature(unsigned, api_key)
    return hmac.compare_digest(expected, signature.strip())


def money_text(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}"


def crypto_text(amount: Decimal) -> str:
    text = f"{amount.quantize(Decimal('0.00000001'))}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def nowpayments_api_url(credentials: dict, sandbox: bool) -> tuple[str, str]:
    """Return (url, error). The URL always ends at /v1, which is where /auth lives."""
    raw = str(credentials.get("api_url") or "").strip()
    if not raw:
        raw = NOWPAYMENTS_SANDBOX if sandbox else NOWPAYMENTS_LIVE
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"} or not host:
        return "", "NOWPayments API URL must be an http(s) address"
    if parsed.username or parsed.password:
        return "", "Put the API key in its own field, not inside the API URL"
    if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1"}:
        return "", "NOWPayments API URL must use HTTPS"
    path = parsed.path.rstrip("/")
    if path.endswith("/auth"):
        path = path[: -len("/auth")].rstrip("/")
    if path in {"", "/"}:
        path = "/v1"
    elif not path.endswith("/v1"):
        path = f"{path}/v1"
    return f"{parsed.scheme}://{parsed.netloc}{path}", ""


def nowpayments_credentials_ready(credentials: dict) -> str:
    api_key = str(credentials.get("api_key") or "").strip()
    ipn_secret = str(credentials.get("ipn_secret") or "").strip()
    email = str(credentials.get("payout_email") or "").strip()
    password = str(credentials.get("payout_password") or "")
    if len(api_key) < 8:
        return "NOWPayments needs an API key"
    if len(ipn_secret) < 8:
        return "NOWPayments needs an IPN secret"
    if "@" not in email or len(email) > 320:
        return "NOWPayments needs the payout email"
    if len(password) < 8:
        return "NOWPayments needs the payout password"
    return ""


class NowPaymentsConnector:
    name = "nowpayments"

    def base_url(self, credentials: dict, sandbox: bool) -> str:
        url, error = nowpayments_api_url(credentials, sandbox)
        if error:
            raise PaymentProviderError(400, error)
        return url

    def probe(self, credentials: dict, *, sandbox: bool, client: httpx.Client | None = None) -> dict:
        missing = nowpayments_credentials_ready(credentials)
        if missing:
            return {"ok": False, "detail": missing}
        url, error = nowpayments_api_url(credentials, sandbox)
        if error:
            return {"ok": False, "detail": error}
        api_key = str(credentials.get("api_key") or "").strip()
        response = self._request("GET", f"{url}/merchant/coins", headers={"x-api-key": api_key}, client=client)
        if response.status_code != 200:
            return {"ok": False, "detail": _error_detail(response, "NOWPayments rejected the API key")}
        email = str(credentials.get("payout_email") or "").strip()
        password = str(credentials.get("payout_password") or "")
        auth = self._request(
            "POST",
            f"{url}/auth",
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            json={"email": email, "password": password},
            client=client,
        )
        token = _safe_token(auth)
        if auth.status_code not in {200, 201} or not token:
            return {"ok": False, "detail": _auth_failure_detail(auth, url, email, password)}
        return {"ok": True, "detail": "NOWPayments accepted the API key and payout login"}

    def create_payment(
        self,
        credentials: dict,
        *,
        sandbox: bool,
        price_amount: Decimal,
        price_currency: str,
        pay_currency: str,
        order_id: str,
        description: str,
        callback_url: str,
        client: httpx.Client | None = None,
    ) -> dict:
        api_key = str(credentials.get("api_key") or "").strip()
        base = self.base_url(credentials, sandbox)
        payload: dict = {
            "price_amount": money_text(price_amount),
            "price_currency": price_currency.lower(),
            "order_id": order_id,
            "order_description": description[:180] or "TradeGuard payment",
            "ipn_callback_url": callback_url,
        }
        path = "/invoice"
        if pay_currency:
            payload["pay_currency"] = pay_currency.lower()
            path = "/payment"
        response = self._request(
            "POST",
            f"{base}{path}",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            client=client,
        )
        if response.status_code not in {200, 201}:
            raise PaymentProviderError(502, _error_detail(response, "NOWPayments did not create a payment"))
        data = _json_object(response)
        provider_id = str(data.get("payment_id") or data.get("id") or "")
        if not provider_id and not data.get("invoice_url"):
            raise PaymentProviderError(502, "NOWPayments returned no payment id")
        return {
            "provider_payment_id": provider_id,
            "invoice_url": str(data.get("invoice_url") or data.get("pay_url") or ""),
            "pay_address": str(data.get("pay_address") or ""),
            "pay_amount": data.get("pay_amount"),
            "pay_currency": str(data.get("pay_currency") or pay_currency or ""),
            "provider_status": str(data.get("payment_status") or "waiting"),
        }

    def create_payout(
        self,
        credentials: dict,
        *,
        sandbox: bool,
        address: str,
        currency: str,
        amount: Decimal,
        callback_url: str,
        client: httpx.Client | None = None,
    ) -> dict:
        api_key = str(credentials.get("api_key") or "").strip()
        base = self.base_url(credentials, sandbox)
        auth = self._request(
            "POST",
            f"{base}/auth",
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            json={"email": str(credentials.get("payout_email") or "").strip(), "password": str(credentials.get("payout_password") or "")},
            client=client,
        )
        token = _safe_token(auth)
        if auth.status_code not in {200, 201} or not token:
            raise PaymentProviderError(502, _auth_failure_detail(auth, base, str(credentials.get("payout_email") or ""), str(credentials.get("payout_password") or "")))
        response = self._request(
            "POST",
            f"{base}/payout",
            headers={"x-api-key": api_key, "Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "ipn_callback_url": callback_url,
                "withdrawals": [{"address": address, "currency": currency.lower(), "amount": crypto_text(amount), "ipn_callback_url": callback_url}],
            },
            client=client,
        )
        if response.status_code not in {200, 201}:
            raise PaymentProviderError(502, _error_detail(response, "NOWPayments did not create a payout"))
        data = _json_object(response)
        withdrawal = data.get("withdrawals")
        first = withdrawal[0] if isinstance(withdrawal, list) and withdrawal and isinstance(withdrawal[0], dict) else data
        provider_id = str(first.get("id") or data.get("id") or "")
        if not provider_id:
            raise PaymentProviderError(502, "NOWPayments returned no payout id")
        return {"provider_id": provider_id, "batch_id": str(data.get("id") or ""), "provider_status": str(first.get("status") or "WAITING")}

    def _request(self, method: str, url: str, *, client: httpx.Client | None, **kwargs) -> httpx.Response:
        return _call("nowpayments", method, url, client=client, **kwargs)


class CryptomusConnector:
    name = "cryptomus"

    def probe(self, credentials: dict, *, sandbox: bool = False, client: httpx.Client | None = None) -> dict:
        merchant = str(credentials.get("merchant_id") or "").strip()
        api_key = str(credentials.get("api_key") or "").strip()
        if len(merchant) < 8 or len(api_key) < 8:
            return {"ok": False, "detail": "Cryptomus needs a merchant id and a payment API key"}
        body: dict = {}
        response = self._request("POST", f"{CRYPTOMUS_LIVE}/payment/services", merchant=merchant, api_key=api_key, body=body, client=client)
        if response.status_code == 200:
            data = _json_object(response)
            if data.get("state") in (0, "0", None) or "result" in data:
                return {"ok": True, "detail": "Cryptomus accepted the merchant credentials"}
        return {"ok": False, "detail": _error_detail(response, "Cryptomus rejected the merchant credentials")}

    def create_payment(
        self,
        credentials: dict,
        *,
        sandbox: bool,
        price_amount: Decimal,
        price_currency: str,
        pay_currency: str,
        order_id: str,
        description: str,
        callback_url: str,
        client: httpx.Client | None = None,
    ) -> dict:
        del sandbox
        merchant = str(credentials.get("merchant_id") or "").strip()
        api_key = str(credentials.get("api_key") or "").strip()
        body: dict = {
            "amount": money_text(price_amount),
            "currency": price_currency.upper(),
            "order_id": order_id,
            "url_callback": callback_url,
            "lifetime": 3600,
            "is_payment_multiple": False,
        }
        if description:
            body["additional_data"] = description[:180]
        if pay_currency:
            body["to_currency"] = pay_currency.upper()
        response = self._request(
            "POST",
            f"{CRYPTOMUS_LIVE}/payment",
            merchant=merchant,
            api_key=api_key,
            body=body,
            client=client,
        )
        if response.status_code not in {200, 201}:
            raise PaymentProviderError(502, _error_detail(response, "Cryptomus did not create a payment"))
        data = _json_object(response)
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        if data.get("state") not in (0, "0", None) and not result.get("uuid"):
            raise PaymentProviderError(502, str(data.get("message") or "Cryptomus did not create a payment"))
        provider_id = str(result.get("uuid") or "")
        if not provider_id:
            raise PaymentProviderError(502, "Cryptomus returned no payment id")
        return {
            "provider_payment_id": provider_id,
            "invoice_url": str(result.get("url") or ""),
            "pay_address": str(result.get("address") or ""),
            "pay_amount": result.get("payer_amount"),
            "pay_currency": str(result.get("payer_currency") or pay_currency or ""),
            "provider_status": str(result.get("payment_status") or "check"),
        }

    def _request(self, method: str, url: str, *, merchant: str, api_key: str, body: dict, client: httpx.Client | None) -> httpx.Response:
        encoded, sign = cryptomus_body(body, api_key)
        return _call(
            "cryptomus",
            method,
            url,
            client=client,
            headers={"merchant": merchant, "sign": sign, "Content-Type": "application/json"},
            content=encoded.encode("utf-8"),
        )


def connector_for(provider: str):
    if provider == "nowpayments":
        return NowPaymentsConnector()
    if provider == "cryptomus":
        return CryptomusConnector()
    return None


def _call(provider: str, method: str, url: str, *, client: httpx.Client | None, **kwargs) -> httpx.Response:
    breaker = _breakers[provider]

    def send(http: httpx.Client) -> httpx.Response:
        response = http.request(method, url, timeout=20.0, **kwargs)
        if response.status_code >= 500:
            raise PaymentProviderError(503, f"{provider} is unavailable")
        return response

    if client is not None:
        return send(client)
    if breaker.is_open:
        raise PaymentProviderError(503, f"{provider} is temporarily unavailable")
    try:
        with httpx.Client() as http:
            return breaker.call(lambda: send(http))
    except CircuitOpen as exc:
        raise PaymentProviderError(503, f"{provider} is temporarily unavailable") from exc
    except PaymentProviderError:
        raise
    except httpx.HTTPError as exc:
        raise PaymentProviderError(503, f"{provider} could not be reached") from exc


def _safe_token(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    if isinstance(data, str) and data.count(".") == 2:
        return data
    if not isinstance(data, dict):
        return ""
    for key in ("token", "jwt", "access_token", "accessToken", "jwtToken"):
        value = data.get(key)
        if value:
            return str(value)
    nested = data.get("data") or data.get("result")
    if isinstance(nested, dict):
        for key in ("token", "jwt", "access_token"):
            value = nested.get(key)
            if value:
                return str(value)
    return ""


def _auth_failure_detail(response: httpx.Response, url: str, email: str, password: str) -> str:
    host = urlparse(url).netloc
    message = _error_detail(response, "")
    lowered = message.lower()
    for secret in (email, password, response.headers.get("x-api-key", "")):
        if secret and secret.lower() in lowered:
            message = ""
            break
    if response.status_code in {301, 302, 307, 308}:
        return f"NOWPayments redirected payout login on {host}. Use https://api.nowpayments.io/v1 for a live account."
    if response.status_code == 404:
        return f"NOWPayments has no payout login at {host}. Use https://api.nowpayments.io/v1 for a live account."
    if message:
        return (
            f"NOWPayments payout login on {host} returned {response.status_code}: {message}. "
            "The dashboard email is case-sensitive, and a live login only works on the live API URL."
        )
    if response.status_code in {400, 401, 403}:
        return (
            f"NOWPayments payout login on {host} returned {response.status_code}. "
            "Use the dashboard email exactly, including capitals. A live login does not work on the sandbox URL."
        )
    return f"NOWPayments payout login on {host} returned {response.status_code}."


def _json_object(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise PaymentProviderError(502, "Payment provider returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise PaymentProviderError(502, "Payment provider returned an unexpected payload")
    return data


def _error_detail(response: httpx.Response, fallback: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return fallback
    if isinstance(data, dict):
        message = data.get("message") or data.get("error") or data.get("status")
        if isinstance(message, str) and message and "key" not in message.lower():
            return message[:240]
    return fallback

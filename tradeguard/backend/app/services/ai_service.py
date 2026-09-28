from __future__ import annotations

import base64
import hashlib
import json
import logging
from decimal import Decimal
from uuid import UUID

import httpx
from sqlalchemy import func, select

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_json, encrypt_json
from app.core.resilience import CircuitBreaker, CircuitOpen
from app.domain.audit import write_audit
from app.models.entities import (
    Account,
    AccountState,
    AiProviderConfig,
    AiRequest,
    ClosedTrade,
    Organization,
    OvertradingRow,
    Position,
    RiskViolation,
    User,
)

_breaker = CircuitBreaker(fail_max=3, reset_seconds=60)

SYSTEM_PROMPT = (
    "You are a risk analyst for a trading desk. Respond with JSON only. "
    "Keys: risk_level (LOW, MEDIUM, HIGH, CRITICAL), observations (array of strings), "
    "possible_causes (array of strings), recommendations (array of strings), "
    "confidence (number from 0 to 1), explanation (string). "
    "Do not propose numeric changes to hard risk limits."
)


class AIProviderError(Exception):
    pass


class OpenAIProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def complete(self, model: str, temperature: float, max_tokens: int, system: str, user: str) -> str:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": model or "gpt-4o-mini",
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
            )
        if response.status_code >= 300:
            raise AIProviderError(f"openai_{response.status_code}")
        return response.json()["choices"][0]["message"]["content"]

    def chat(self, model: str, temperature: float, max_tokens: int, messages: list, tools: list | None = None) -> dict:
        payload: dict = {
            "model": model or "gpt-4o-mini",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code >= 300:
            raise AIProviderError(f"openai_{response.status_code}")
        message = response.json()["choices"][0]["message"]
        return message if isinstance(message, dict) else {"role": "assistant", "content": str(message)}


class AnthropicProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete(self, model: str, temperature: float, max_tokens: int, system: str, user: str) -> str:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": model or "claude-3-5-sonnet-latest",
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
        if response.status_code >= 300:
            raise AIProviderError(f"anthropic_{response.status_code}")
        body = response.json()
        return "".join(part.get("text", "") for part in body.get("content", []))


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete(self, model: str, temperature: float, max_tokens: int, system: str, user: str) -> str:
        chosen = model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{chosen}:generateContent?key={self.api_key}"
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
                },
            )
        if response.status_code >= 300:
            raise AIProviderError(f"gemini_{response.status_code}")
        candidates = response.json().get("candidates") or []
        parts = candidates[0]["content"]["parts"] if candidates else []
        return "".join(part.get("text", "") for part in parts)


class LocalAIProvider(OpenAIProvider):
    pass


DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/v1"
OPENAI_URL = "https://api.openai.com/v1"
OPENAI_VISION_MODEL = "gpt-4o"
OPENAI_IMAGE_MODEL = "gpt-image-1"


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek's chat API uses the OpenAI request shape."""

    def __init__(self, api_key: str, base_url: str = DEEPSEEK_URL) -> None:
        super().__init__(api_key, DEEPSEEK_URL)

    def complete(self, model: str, temperature: float, max_tokens: int, system: str, user: str) -> str:
        return super().complete(model or DEEPSEEK_MODEL, temperature, max_tokens, system, user)

    def chat(self, model: str, temperature: float, max_tokens: int, messages: list, tools: list | None = None) -> dict:
        return super().chat(model or DEEPSEEK_MODEL, temperature, max_tokens, messages, tools)


AI_PROVIDERS = {"openai", "gemini", "anthropic", "local", "deepseek"}


def provider_for(name: str, api_key: str, base_url: str):
    if name == "anthropic":
        return AnthropicProvider(api_key)
    if name == "gemini":
        return GeminiProvider(api_key)
    if name == "local":
        return LocalAIProvider(api_key, base_url or "http://localhost:11434/v1")
    if name == "deepseek":
        return DeepSeekProvider(api_key, DEEPSEEK_URL)
    return OpenAIProvider(api_key, base_url or "https://api.openai.com/v1")


def build_context(db: Session, account: Account) -> dict:
    state = db.get(AccountState, account.id)
    open_rows = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    recent = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account.id).order_by(ClosedTrade.close_time.desc()).limit(20)).all()
    violations = db.scalars(
        select(RiskViolation).where(RiskViolation.account_id == account.id, RiskViolation.status == "open").limit(20)
    ).all()
    overtrading = db.scalar(select(OvertradingRow).where(OvertradingRow.account_id == account.id).order_by(OvertradingRow.created_at.desc()))
    exposure = sum((abs(row.volume * row.current_price) for row in open_rows), Decimal("0"))
    return {
        "account": {
            "name": account.display_name,
            "currency": account.currency,
            "status": account.status,
            "control_state": account.control_state,
        },
        "summary": {
            "balance": str(state.balance if state else 0),
            "equity": str(state.equity if state else 0),
            "margin_level": None if not state or state.margin_level is None else str(state.margin_level),
            "peak_equity": str(state.peak_equity if state else 0),
        },
        "exposure": str(exposure),
        "open_positions": [
            {"symbol": row.symbol, "side": row.side, "volume": str(row.volume), "profit": str(row.profit)}
            for row in open_rows
        ],
        "recent_trades": [
            {"symbol": row.symbol, "profit": str(row.profit), "volume": str(row.volume)}
            for row in recent
        ],
        "violations": [{"code": row.code, "severity": row.severity} for row in violations],
        "overtrading": None if overtrading is None else {"state": overtrading.state, "metrics": overtrading.metrics},
    }


def parse_analysis(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {
            "risk_level": "UNKNOWN",
            "observations": [],
            "possible_causes": [],
            "recommendations": [],
            "confidence": 0,
            "explanation": raw[:2000],
        }
    level = str(data.get("risk_level") or "UNKNOWN").upper()
    if level not in {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}:
        level = "UNKNOWN"
    return {
        "risk_level": level,
        "observations": [str(item) for item in data.get("observations") or []],
        "possible_causes": [str(item) for item in data.get("possible_causes") or []],
        "recommendations": [str(item) for item in data.get("recommendations") or []],
        "confidence": float(data.get("confidence") or 0),
        "explanation": str(data.get("explanation") or ""),
    }


def analyze_account(db: Session, user: User, account: Account, provider=None) -> dict:
    config = db.scalar(select(AiProviderConfig).where(AiProviderConfig.organization_id == user.organization_id))
    context = build_context(db, account)
    context_hash = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    if provider is None:
        if config is None or not config.enabled or not config.secret_ciphertext:
            result = {
                "risk_level": "UNKNOWN",
                "observations": [],
                "possible_causes": [],
                "recommendations": [],
                "confidence": 0,
                "explanation": "AI provider is not configured for this organization.",
            }
            _store(db, user, account, config, context_hash, result, "not_configured")
            return result
        secret = decrypt_json(config.secret_nonce, config.secret_ciphertext)
        provider = provider_for(config.provider, str(secret.get("api_key") or ""), config.base_url)
        model = config.model
        temperature = float(config.temperature)
        max_tokens = config.max_tokens
    else:
        model, temperature, max_tokens = "test", 0.0, 400
    try:
        raw = _breaker.call(
            lambda: provider.complete(model, temperature, max_tokens, SYSTEM_PROMPT, json.dumps(context))
        )
        parsed = parse_analysis(raw)
        status = "completed"
        error = ""
    except CircuitOpen:
        parsed = parse_analysis("")
        parsed["explanation"] = "AI circuit is open. Deterministic risk limits are unchanged."
        parsed["risk_level"] = "UNKNOWN"
        status = "circuit_open"
        error = "ai_circuit_open"
    except Exception as exc:  # noqa: BLE001
        parsed = parse_analysis("")
        parsed["explanation"] = "AI provider failed. Deterministic risk limits are unchanged."
        parsed["risk_level"] = "UNKNOWN"
        status = "failed"
        error = exc.__class__.__name__
    _store(db, user, account, config, context_hash, parsed, error, status)
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="ai_request",
        entity_type="account",
        entity_id=str(account.id),
        after={"status": status, "risk_level": parsed["risk_level"]},
    )
    return parsed


def save_ai_config(db: Session, organization_id: UUID, payload: dict) -> AiProviderConfig:
    row = db.scalar(select(AiProviderConfig).where(AiProviderConfig.organization_id == organization_id))
    if row is None:
        row = AiProviderConfig(organization_id=organization_id)
        db.add(row)
    provider = payload.get("provider") or row.provider
    if provider not in AI_PROVIDERS:
        raise ValueError("Unsupported AI provider")
    secret = _read_ai_secret(row)
    if provider == "openai":
        key = str(payload.get("api_key") or "").strip()
        if not key and not secret.get("openai_api_key"):
            raise ValueError("Enter the OpenAI API key")
        if key:
            secret["openai_api_key"] = key
        if row.provider != "deepseek":
            row.provider = "openai"
            row.model = OPENAI_VISION_MODEL
            row.base_url = OPENAI_URL
            if key:
                secret["api_key"] = key
        _write_ai_secret(row, secret)
        return row
    row.provider = provider
    if provider == "deepseek":
        row.model = DEEPSEEK_MODEL
        row.base_url = DEEPSEEK_URL
    else:
        row.model = payload.get("model") or ""
        if payload.get("base_url") is not None:
            row.base_url = payload["base_url"]
    if payload.get("temperature") is not None and provider != "deepseek":
        row.temperature = Decimal(str(payload["temperature"]))
    if payload.get("max_tokens") is not None and provider != "deepseek":
        row.max_tokens = int(payload["max_tokens"])
    if payload.get("enabled") is not None:
        row.enabled = bool(payload["enabled"])
    if payload.get("api_key") and provider != "openai":
        secret["api_key"] = payload["api_key"]
        _write_ai_secret(row, secret)
    return row


def _read_ai_secret(row: AiProviderConfig) -> dict:
    if not row.secret_nonce or not row.secret_ciphertext:
        return {}
    data = decrypt_json(row.secret_nonce, row.secret_ciphertext)
    return data if isinstance(data, dict) else {}


def _write_ai_secret(row: AiProviderConfig, secret: dict) -> None:
    nonce, ciphertext = encrypt_json(secret)
    row.secret_nonce = nonce
    row.secret_ciphertext = ciphertext


def integration_status(db: Session, organization_id: UUID) -> list[dict]:
    from app.services.alert_service import _telegram, _telegram_secret

    row = db.scalar(select(AiProviderConfig).where(AiProviderConfig.organization_id == organization_id))
    secret = _read_ai_secret(row) if row is not None else {}
    deepseek_key = str(secret.get("api_key") or "") if row is not None and row.provider == "deepseek" and row.enabled else ""
    openai_key = str(secret.get("openai_api_key") or "")
    telegram = _telegram_secret(db, organization_id)
    token = str(telegram.get("bot_token") or "")
    telegram_ok = False
    if token:
        try:
            telegram_ok = bool(_telegram(token, "getMe").get("ok"))
        except Exception:
            telegram_ok = False
    from app.services.email_service import email_credentials, resend_connected

    accounts = db.scalars(select(Account).where(Account.organization_id == organization_id, Account.connection_method == "metaapi")).all()
    resend_key, _sender = email_credentials(db, organization_id)
    return [
        {"name": "DeepSeek", "connected": _models_ok(DEEPSEEK_URL, deepseek_key)},
        {"name": "OpenAI", "connected": _models_ok(OPENAI_URL, openai_key)},
        {"name": "Resend", "connected": resend_connected(resend_key)},
        {"name": "Telegram", "connected": telegram_ok},
        {"name": "Telegram account", "connected": bool(telegram.get("user_session")) and bool(telegram.get("user_connected"))},
        {"name": "MetaAPI", "connected": any(account.status == "connected" for account in accounts)},
    ]


def _models_ok(base_url: str, api_key: str) -> bool:
    if not api_key:
        return False
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError:
        return False
    return response.status_code < 300


def openai_api_key(db: Session, organization_id: UUID) -> str:
    row = db.scalar(select(AiProviderConfig).where(AiProviderConfig.organization_id == organization_id))
    if row is None:
        return ""
    return str(_read_ai_secret(row).get("openai_api_key") or "")


def describe_image(api_key: str, image: bytes, mime: str, caption: str) -> str:
    encoded = base64.b64encode(image).decode("ascii")
    prompt = caption.strip() or "Read this image for a trader."
    with httpx.Client(timeout=45) as client:
        response = client.post(
            f"{OPENAI_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": OPENAI_VISION_MODEL,
                "max_tokens": 700,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You read chart images for a trader. "
                            "Name the instrument exactly as printed on the chart. "
                            "State the direction as buy or sell when a long or short position is drawn. "
                            "Give the entry, stop loss, and take profit as prices when those numbers are visible. "
                            "If only a distance is printed, report that distance and do not invent the missing price. "
                            "Do not place trades."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt[:1000]},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                        ],
                    },
                ],
            },
        )
    if response.status_code >= 300:
        raise AIProviderError("openai_image_read_failed")
    message = response.json()["choices"][0]["message"]["content"]
    return str(message or "").strip() or "OpenAI did not describe that image."


def create_image(api_key: str, prompt: str) -> bytes:
    text = prompt.strip()[:1000]
    if not text:
        raise AIProviderError("openai_image_prompt_missing")
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{OPENAI_URL}/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": OPENAI_IMAGE_MODEL, "prompt": text, "size": "1024x1024"},
        )
        if response.status_code >= 300:
            response = client.post(
                f"{OPENAI_URL}/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "dall-e-3", "prompt": text, "size": "1024x1024", "response_format": "b64_json"},
            )
    if response.status_code >= 300:
        raise AIProviderError("openai_image_create_failed")
    data = (response.json().get("data") or [{}])[0]
    encoded = str(data.get("b64_json") or "")
    if not encoded and data.get("url"):
        with httpx.Client(timeout=30) as client:
            downloaded = client.get(str(data["url"]))
        if downloaded.status_code >= 300:
            raise AIProviderError("openai_image_create_failed")
        return downloaded.content
    if not encoded:
        raise AIProviderError("openai_image_create_failed")
    try:
        return base64.b64decode(encoded)
    except ValueError as exc:
        raise AIProviderError("openai_image_create_failed") from exc


def _store(db, user, account, config, context_hash, parsed, error, status="completed") -> None:
    db.add(
        AiRequest(
            organization_id=user.organization_id,
            account_id=account.id,
            provider="" if config is None else config.provider,
            model="" if config is None else config.model,
            status=status,
            context_hash=context_hash,
            response=parsed,
            error_code=error,
        )
    )


def count_rules(db: Session, organization_id) -> int:
    return db.scalar(select(func.count()).select_from(AiRequest).where(AiRequest.organization_id == organization_id)) or 0


TRADE_SYSTEM = (
    "You are the TradeGuard trade assistant for one MetaAPI account. "
    "Use tools to read prices and positions and to open, close, set breakeven, change stops, or place a limit. "
    "Do not invent fills. If a tool returns sent false, report the decision and stop. "
    "If a tool returns sent true and says the stop was rejected, the limit is working without that stop. Say that, and do not describe it as a failed order. "
    "When the user does not give a lot size, use that symbol's Deriv minimum. When the user does not give a stop, omit stop_loss so the desk sets 100 pips and a 2R target. "
    "You cannot change risk limits, pause the account, or trade a different account. "
    "Call create_image when a picture would answer the user. Do not say an image was sent unless that tool returns image_ready true."
)


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TRADE_TOOLS = [
    _fn("list_positions", "List open trades on this account.", {}, []),
    _fn(
        "get_price",
        "Read the current bid and ask. VIX means a Volatility index such as Volatility 75 Index, never the ticker VIX.",
        {"symbol": {"type": "string"}},
        ["symbol"],
    ),
    _fn(
        "open_trade",
        "Open a market trade. Pass a broker symbol. VIX 75 is Volatility 75 Index. The risk engine can block it.",
        {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "volume": {"type": "number"},
            "stop_loss": {"type": "number"},
            "take_profit": {"type": "number"},
        },
        ["symbol", "side", "volume"],
    ),
    _fn("close_trade", "Close one open trade by ticket.", {"ticket": {"type": "string"}}, ["ticket"]),
    _fn("set_breakeven", "Move the stop to the open price.", {"ticket": {"type": "string"}}, ["ticket"]),
    _fn(
        "set_stops",
        "Set the stop loss and take profit on an open trade.",
        {"ticket": {"type": "string"}, "stop_loss": {"type": "number"}, "take_profit": {"type": "number"}},
        ["ticket"],
    ),
    _fn(
        "place_limit",
        "Place a pending limit order. The risk engine can block it.",
        {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "volume": {"type": "number"},
            "price": {"type": "number"},
            "stop_loss": {"type": "number"},
            "take_profit": {"type": "number"},
        },
        ["symbol", "side", "volume", "price"],
    ),
    _fn("create_image", "Create an image with OpenAI and send it on Telegram.", {"prompt": {"type": "string"}}, ["prompt"]),
]


_SIGNAL_SYSTEM = (
    "You read one Telegram message and decide if it is a trade signal. "
    "A signal must contain a market pair, a direction of buy or sell, and an entry price. "
    "Stop loss and take profit may be missing. Lot size may be missing. "
    "A greeting, a result, news, or ordinary chat is not a signal. "
    "Reply with JSON only. Use {\"signal\": false} when it is not a signal. "
    "Use {\"signal\": true, \"symbol\": \"EURUSD\", \"side\": \"buy\", \"entry\": 1.085, \"stop_loss\": null, \"take_profit\": null, \"volume\": null} when it is. "
    "Use null when stop, target, or volume is not written. Do not invent prices."
)


def extract_signal(db: Session, organization_id: UUID, text: str) -> dict | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    config = db.scalar(select(AiProviderConfig).where(AiProviderConfig.organization_id == organization_id))
    if config is None or not config.enabled or config.provider != "deepseek" or not config.secret_ciphertext:
        return None
    secret = decrypt_json(config.secret_nonce, config.secret_ciphertext)
    provider = provider_for("deepseek", str(secret.get("api_key") or ""), DEEPSEEK_URL)
    try:
        raw = provider.complete(DEEPSEEK_MODEL, 0, 300, _SIGNAL_SYSTEM, cleaned[:2000])
    except Exception:
        logger.warning("telegram_signal_read_failed")
        return None
    return parse_signal_reply(raw)


def parse_signal_reply(raw: str) -> dict | None:
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("signal") is not True:
        return None
    symbol = str(data.get("symbol") or "").strip()
    side = str(data.get("side") or "").strip().lower()
    if side == "long":
        side = "buy"
    if side == "short":
        side = "sell"
    entry = _signal_number(data.get("entry"))
    if not symbol or side not in {"buy", "sell"} or entry is None:
        return None
    volume = _signal_number(data.get("volume"))
    return {
        "symbol": symbol[:64],
        "side": side,
        "entry": entry,
        "stop_loss": _signal_number(data.get("stop_loss")),
        "take_profit": _signal_number(data.get("take_profit")),
        "volume": volume,
    }


def _signal_number(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


def run_trade_assistant(
    db: Session,
    user: User,
    account: Account,
    message: str,
    images: list | None = None,
    source: str = "DeepSeek",
    history: list | None = None,
) -> dict:
    from app.services.order_service import OrderError, account_symbols, list_open_positions, minimum_volume_guide, place_order, read_price, symbol_guide

    if not account.ai_trading_enabled:
        raise OrderError(403, "DeepSeek trading is off for this account")
    config = db.scalar(select(AiProviderConfig).where(AiProviderConfig.organization_id == user.organization_id))
    if config is None or not config.enabled or config.provider != "deepseek" or not config.secret_ciphertext:
        raise OrderError(400, "Enable DeepSeek in AI settings before using the trade assistant")
    secret = decrypt_json(config.secret_nonce, config.secret_ciphertext)
    provider = provider_for("deepseek", str(secret.get("api_key") or ""), config.base_url)
    blocks = (
        " Risk blocks are paused on this account. Place the order. If the decision is BLOCK or EMERGENCY_STOP and sent is true, tell the user the order was sent and quote that decision. Do not refuse it."
        if account.risk_blocks_paused
        else " Risk blocks are enforced. If sent is false, give the decision in one sentence and say Pause risk blocks on the ticket will send the next order."
    )
    prior = [
        {"role": item["role"], "content": str(item.get("content") or "")[:1500]}
        for item in (history or [])
        if isinstance(item, dict) and item.get("role") in {"user", "assistant"} and str(item.get("content") or "").strip()
    ]
    context = ""
    if prior:
        context = (
            " Earlier messages in this Telegram chat are the same conversation. "
            "When the user says that, this, or the chart, use the instrument, direction, entry, stop, and target already stated. "
            "Do not ask again for a value that is already in the conversation. "
            "If the user does not name a lot size, use that symbol's minimum volume."
        )
    messages: list[dict] = [
        {"role": "system", "content": TRADE_SYSTEM + " " + symbol_guide(account_symbols(db, account)) + minimum_volume_guide(db, account) + blocks + context},
        *prior[-8:],
        {"role": "user", "content": message.strip()[:2000]},
    ]
    steps: list[dict] = []
    reply = ""
    for _ in range(4):
        try:
            assistant = provider.chat(config.model or DEEPSEEK_MODEL, float(config.temperature), config.max_tokens, messages, TRADE_TOOLS)
        except Exception as exc:  # noqa: BLE001
            raise OrderError(502, "DeepSeek did not answer") from exc
        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            reply = str(assistant.get("content") or "")
            break
        messages.append(assistant)
        for call in tool_calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            outcome = _dispatch_tool(db, user, account, name, args, list_open_positions, place_order, read_price, OrderError, images, source)
            steps.append({"tool": name, "result": outcome})
            messages.append({"role": "tool", "tool_call_id": str(call.get("id") or name), "content": json.dumps(outcome, default=str)})
    else:
        reply = reply or "Stopped after four tool rounds."
    return {"reply": reply or "Done.", "steps": steps}


def _dispatch_tool(db, user, account, name, args, list_open_positions, place_order, read_price, order_error, images=None, source: str = "DeepSeek") -> dict:
    try:
        if name == "list_positions":
            return {"positions": list_open_positions(db, account)}
        if name == "get_price":
            return read_price(db, account, str(args.get("symbol") or ""))
        if name == "open_trade":
            return place_order(db, user, account, {**args, "action": "open", "source": source}, actor="ai")
        if name == "close_trade":
            return place_order(db, user, account, {"action": "close", "ticket": args.get("ticket")}, actor="ai")
        if name == "set_breakeven":
            return place_order(db, user, account, {"action": "breakeven", "ticket": args.get("ticket")}, actor="ai")
        if name == "set_stops":
            return place_order(
                db,
                user,
                account,
                {"action": "modify", "ticket": args.get("ticket"), "stop_loss": args.get("stop_loss"), "take_profit": args.get("take_profit")},
                actor="ai",
            )
        if name == "place_limit":
            return place_order(db, user, account, {**args, "action": "limit", "source": source}, actor="ai")
        if name == "create_image":
            return _create_image_tool(db, account, args, images)
    except order_error as exc:
        return {"sent": False, "decision": "BLOCK", "message": exc.detail}
    return {"sent": False, "message": "Unknown tool"}


def _create_image_tool(db: Session, account: Account, args: dict, images: list | None) -> dict:
    if images is None:
        return {"image_ready": False, "message": "Images are delivered on Telegram."}
    prompt = str(args.get("prompt") or "").strip()
    key = openai_api_key(db, account.organization_id)
    if not key:
        return {"image_ready": False, "message": "Save an OpenAI API key in Settings."}
    try:
        images.append(create_image(key, prompt))
    except AIProviderError:
        return {"image_ready": False, "message": "OpenAI could not create that image."}
    return {"image_ready": True, "message": "The image will be sent in this chat."}

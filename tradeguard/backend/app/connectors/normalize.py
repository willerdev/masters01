from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.connectors.types import NormalizedAccount, NormalizedPosition, NormalizedQuote

_BUY = {"buy", "long", "0", "position_type_buy", "op_buy"}
_SELL = {"sell", "short", "1", "position_type_sell", "op_sell"}


class NormalizeError(ValueError):
    pass


def _dec(value: object, field: str, default: str | None = None) -> Decimal:
    if value is None or value == "":
        if default is None:
            raise NormalizeError(f"missing {field}")
        value = default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizeError(f"invalid {field}") from exc


def _optional_dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return _dec(value, "number")


def _first(data: dict, *keys: str, default: object = None) -> object:
    for key in keys:
        if key in data and data[key] is not None and data[key] != "":
            return data[key]
    return default


def _side(value: object) -> str:
    if value is None or value == "":
        raise NormalizeError("missing side")
    text = str(value).strip().lower()
    if text in _BUY:
        return "buy"
    if text in _SELL:
        return "sell"
    raise NormalizeError(f"unknown side {value}")


def _time(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NormalizeError("invalid timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def canonical_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    for suffix in (".PRO", ".RAW", ".ECN", ".M", ".R", ".CASH", "PRO", "M", ".S"):
        if text.endswith(suffix) and len(text) > len(suffix) + 3:
            text = text[: -len(suffix)]
            break
    return text


def normalize_position(data: dict, account_id: str | None = None) -> NormalizedPosition:
    if not isinstance(data, dict):
        raise NormalizeError("position payload must be an object")
    symbol = str(_first(data, "symbol", "Symbol", default="")).strip()
    if not symbol:
        raise NormalizeError("missing symbol")
    ticket = str(_first(data, "ticket", "position_id", "positionId", "id", default="")).strip()
    if not ticket:
        raise NormalizeError("missing ticket")
    open_time = _time(_first(data, "open_time", "openTime", "time"))
    return NormalizedPosition(
        account_id=account_id or (str(data["account_id"]) if data.get("account_id") else None),
        ticket=ticket,
        symbol=symbol,
        side=_side(_first(data, "side", "type", "direction", "positionType")),
        volume=_dec(_first(data, "volume", "lots", "Volume"), "volume"),
        entry_price=_dec(_first(data, "entry_price", "entryPrice", "price_open", "priceOpen", "openPrice", "open_price"), "entry_price"),
        current_price=_dec(
            _first(data, "current_price", "currentPrice", "price_current", "priceCurrent", "price", default="0"),
            "current_price",
            "0",
        ),
        stop_loss=_optional_dec(_first(data, "stop_loss", "stopLoss", "sl", "SL")),
        take_profit=_optional_dec(_first(data, "take_profit", "takeProfit", "tp", "TP")),
        profit=_dec(_first(data, "profit", "floating_pl", "profitLoss", default="0"), "profit", "0"),
        swap=_dec(_first(data, "swap", default="0"), "swap", "0"),
        commission=_dec(_first(data, "commission", default="0"), "commission", "0"),
        open_time=open_time,
        magic_number=int(_first(data, "magic_number", "magicNumber", "magic", default=0) or 0),
        comment=str(_first(data, "comment", "strategy", default="") or "")[:200],
    )


def normalize_account(data: dict) -> NormalizedAccount:
    if not isinstance(data, dict):
        raise NormalizeError("account payload must be an object")
    margin_level = _optional_dec(_first(data, "margin_level", "marginLevel"))
    return NormalizedAccount(
        balance=_dec(_first(data, "balance", "Balance", default="0"), "balance", "0"),
        equity=_dec(_first(data, "equity", "Equity", default="0"), "equity", "0"),
        margin=_dec(_first(data, "margin", "Margin", default="0"), "margin", "0"),
        free_margin=_dec(_first(data, "free_margin", "freeMargin", "margin_free", default="0"), "free_margin", "0"),
        margin_level=margin_level,
        currency=str(_first(data, "currency", default="USD") or "USD"),
    )


def normalize_quote(data: dict, *, source: str, now: datetime | None = None) -> NormalizedQuote:
    if not isinstance(data, dict):
        raise NormalizeError("quote payload must be an object")
    symbol = str(_first(data, "symbol", default="")).strip()
    if not symbol:
        raise NormalizeError("missing symbol")
    bid = _dec(_first(data, "bid", "Bid"), "bid")
    ask = _dec(_first(data, "ask", "Ask"), "ask")
    spread = _optional_dec(_first(data, "spread"))
    if spread is None:
        spread = ask - bid
    captured = _time(_first(data, "timestamp", "time")) or now or datetime.now(timezone.utc)
    return NormalizedQuote(
        symbol=symbol,
        bid=bid,
        ask=ask,
        spread=spread,
        tick_size=_optional_dec(_first(data, "tick", "tick_size", "tickSize")),
        timestamp=captured,
        source=source,
    )

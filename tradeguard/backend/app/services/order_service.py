from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.metaapi import MetaApiConnector
from app.core.encryption import encrypt_json
from app.core.security import sha256_hex
from app.domain.audit import write_audit
from app.models.entities import Account, AccountCredential, ClosedTrade, Position, SymbolSpecRow, User
from app.services.account_service import load_credentials
from app.services.ingest_service import _evaluate, _fx, _maybe_store_spec, _spec_for
from tradeguard_risk.types import Decision, ProposedOrder, SymbolSpec

_OPEN = {"open", "limit"}
_PROTECTIVE = {"close", "breakeven", "modify"}


class OrderError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def place_order(db: Session, user: User, account: Account, payload: dict, *, actor: str = "user") -> dict:
    action = str(payload.get("action") or "")
    if action not in _OPEN | _PROTECTIVE:
        raise OrderError(400, "Unsupported order")
    if account.connection_method != "metaapi":
        raise OrderError(400, "This connection cannot place trades")
    credentials = load_credentials(db, account.id)
    if not credentials.get("token") or not credentials.get("metaapi_account_id"):
        raise OrderError(400, "MetaAPI credentials are missing")
    if action in _PROTECTIVE and account.control_state == "EMERGENCY_STOP":
        return _finish(
            db,
            user,
            account,
            action,
            "",
            None,
            "EMERGENCY_STOP",
            [],
            {"ok": False, "numeric_code": 0, "message": "Account is in emergency stop", "order_id": "", "position_id": ""},
            actor,
            sent=False,
        )
    if action in _OPEN:
        return _open(db, user, account, credentials, payload, action, actor)
    return _protect(db, user, account, credentials, payload, action, actor)


def list_open_positions(db: Session, account: Account) -> list[dict]:
    rows = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    return [
        {
            "ticket": row.ticket,
            "symbol": row.symbol,
            "side": row.side,
            "volume": str(row.volume),
            "entry": str(row.entry_price),
            "price": str(row.current_price),
            "stop_loss": None if row.stop_loss is None else str(row.stop_loss),
            "take_profit": None if row.take_profit is None else str(row.take_profit),
            "profit": str(row.profit),
        }
        for row in rows
    ]


def read_price(db: Session, account: Account, symbol: str) -> dict:
    if account.connection_method != "metaapi":
        raise OrderError(400, "This connection cannot place trades")
    symbol = resolve_broker_symbol(symbol, account_symbols(db, account))
    credentials = load_credentials(db, account.id)
    try:
        quote = MetaApiConnector().fetch_quote(credentials, symbol)
    except Exception as exc:  # noqa: BLE001
        raise OrderError(400, "The terminal did not return a price") from exc
    return {"symbol": quote.symbol or symbol, "bid": str(quote.bid), "ask": str(quote.ask)}


def _open(db: Session, user: User, account: Account, credentials: dict, payload: dict, action: str, actor: str) -> dict:
    symbol = resolve_broker_symbol(str(payload.get("symbol") or ""), account_symbols(db, account))
    side = str(payload.get("side") or "").lower()
    if not symbol:
        raise OrderError(400, "Enter a symbol")
    if side not in {"buy", "sell"}:
        raise OrderError(400, "Choose buy or sell")
    raw_volume = payload.get("volume")
    volume = None if raw_volume in (None, "") else _decimal(raw_volume, "a volume")
    stop = _optional(payload.get("stop_loss"))
    take = _optional(payload.get("take_profit"))
    limit = _optional(payload.get("price")) if action == "limit" else None
    if action == "limit" and (limit is None or limit <= 0):
        raise OrderError(400, "Enter a limit price")
    try:
        quote = MetaApiConnector().fetch_quote(credentials, symbol)
    except Exception as exc:  # noqa: BLE001
        raise OrderError(400, "The terminal did not return a price") from exc
    entry = limit if limit is not None else (quote.ask if side == "buy" else quote.bid)
    try:
        raw_spec = MetaApiConnector().fetch_symbol_spec(credentials, symbol)
    except Exception:  # noqa: BLE001
        raw_spec = None
    if raw_spec:
        _maybe_store_spec(db, account, raw_spec, symbol)
    spec = _spec_for(db, account, symbol)
    from app.connectors.synthetic_lots import minimum_lot, pip_size, plan_protection

    volume_note = ""
    floor = minimum_lot(symbol)
    if floor is not None and spec.tick_size <= 0 and spec.contract_size <= 0:
        from dataclasses import replace

        spec = replace(spec, volume_min=floor, volume_step=floor)
    if volume is None:
        volume = floor or (spec.volume_min if spec.volume_min > 0 else Decimal("0.01"))
    elif floor is not None and volume < floor:
        volume_note = f"Volume was raised from {_plain_lot(volume)} to {_plain_lot(floor)}, the Deriv minimum for {symbol}."
        volume = floor
    if volume <= 0:
        raise OrderError(400, "Enter a volume")
    pip = pip_size(symbol, spec)
    auto_stop = False
    auto_target = take is None
    if actor == "ai" and stop is None:
        stop, take, auto_stop, auto_target = plan_protection(side, entry, None, take, pip, 100)
    elif actor == "ai" and take is None:
        _, take, _, auto_target = plan_protection(side, entry, stop, None, pip, 100)
    fitted = _fit_volume(volume, spec)
    if fitted != volume:
        raised = f"Volume was raised from {_plain_lot(volume)} to {_plain_lot(fitted)}, the minimum for {symbol}."
        volume_note = f"{volume_note} {raised}".strip()
        volume = fitted
    proposed = ProposedOrder(symbol, side, volume, entry, stop, take)
    result = _evaluate(db, account, datetime.now(timezone.utc), f"desk-{uuid4().hex}", proposed, spec, _fx(account, spec))
    hits = [
        {"code": hit.code, "decision": hit.decision.value, "message": hit.message}
        for hit in result.hits
    ]
    from app.services.fund_service import mandate_hits

    mandate = mandate_hits(db, account, symbol, volume, entry)
    hits.extend(mandate)
    mandate_block = any(hit["decision"] == Decision.BLOCK.value for hit in mandate)
    decision = Decision.BLOCK if mandate_block and result.decision in {Decision.ALLOW, Decision.WARNING} else result.decision
    source = _source_comment(payload, actor)
    paused = bool(account.risk_blocks_paused)
    if decision not in {Decision.ALLOW, Decision.WARNING} and not paused:
        blocked = next((hit["message"] for hit in hits if hit["decision"] in {Decision.BLOCK.value, Decision.EMERGENCY_STOP.value}), "Order blocked")
        return _finish(
            db,
            user,
            account,
            action,
            symbol,
            volume,
            decision.value,
            hits,
            {"ok": False, "numeric_code": 0, "message": blocked, "order_id": "", "position_id": ""},
            actor,
            sent=False,
            source=source,
        )
    body = _broker_open(action, symbol, side, volume, stop, take, limit, source)
    broker = MetaApiConnector().trade(credentials, body)
    broker, stop_note, naked_stop = _retry_without_rejected_stop(
        action, symbol, side, volume, stop, take, limit, source, credentials, broker, auto_stop, auto_target, pip, entry
    )
    if broker.get("ok"):
        _remember_source(db, account, str(broker.get("position_id") or broker.get("order_id") or ""), source)
        if auto_stop and not stop_note and stop is not None:
            target_text = f" Target is 2R at {_plain_lot(take)}." if auto_target and take is not None else ""
            stop_note = f"No stop was given, so the stop is 100 pips at {_plain_lot(stop)}.{target_text}"
        if naked_stop is not None:
            _remember_naked_limit(db, account, broker, symbol, side, entry, volume, naked_stop)
        if stop_note:
            broker = {**broker, "message": f"{stop_note} {broker.get('message') or ''}".strip()}
    if paused and broker.get("ok") and decision not in {Decision.ALLOW, Decision.WARNING}:
        note = next((hit["message"] for hit in hits if hit["decision"] in {Decision.BLOCK.value, Decision.EMERGENCY_STOP.value}), "")
        if note:
            broker = {**broker, "message": f"Risk blocks are paused. {note}"}
    if volume_note:
        broker = {**broker, "message": f"{volume_note} {broker.get('message') or ''}".strip()}
    return _finish(
        db,
        user,
        account,
        action,
        symbol,
        volume,
        decision.value,
        hits,
        broker,
        actor,
        sent=bool(broker["ok"]),
        risk_blocks_paused=paused,
        source=source,
    )


def _protect(db: Session, user: User, account: Account, credentials: dict, payload: dict, action: str, actor: str) -> dict:
    ticket = str(payload.get("ticket") or "").strip()
    if not ticket:
        raise OrderError(400, "Choose a trade")
    position = db.scalar(
        select(Position).where(Position.account_id == account.id, Position.ticket == ticket, Position.status == "open")
    )
    if position is None:
        raise OrderError(404, "Open trade not found")
    if action == "close":
        body = {"actionType": "POSITION_CLOSE_ID", "positionId": ticket}
    elif action == "breakeven":
        body = {"actionType": "POSITION_MODIFY", "positionId": ticket, "stopLoss": _num(position.entry_price)}
        if position.take_profit is not None:
            body["takeProfit"] = _num(position.take_profit)
    else:
        stop = _optional(payload.get("stop_loss"))
        take = _optional(payload.get("take_profit"))
        if stop is None and take is None:
            raise OrderError(400, "Enter a stop or a limit")
        body = {"actionType": "POSITION_MODIFY", "positionId": ticket}
        if stop is not None:
            body["stopLoss"] = _num(stop)
        if take is not None:
            body["takeProfit"] = _num(take)
    broker = MetaApiConnector().trade(credentials, body)
    return _finish(
        db,
        user,
        account,
        action,
        position.symbol,
        position.volume,
        "ALLOW" if broker["ok"] else "BLOCK",
        [],
        broker,
        actor,
        sent=bool(broker["ok"]),
    )


def trade_source(name: str) -> str:
    """Broker comments are short. Keep the source readable inside that limit."""
    cleaned = "".join(ch if ch.isalnum() or ch in " .+-_" else " " for ch in str(name or ""))
    cleaned = " ".join(cleaned.split())[:26].strip()
    return cleaned or "Telegram"


def _source_comment(payload: dict, actor: str) -> str:
    if actor == "ai":
        return trade_source(str(payload.get("source") or "DeepSeek"))
    return "Desk"


def _remember_source(db: Session, account: Account, ticket: str, source: str) -> None:
    ticket = str(ticket or "").strip()
    if not ticket or not source:
        return
    row = db.scalar(select(Position).where(Position.account_id == account.id, Position.ticket == ticket))
    if row is None:
        return
    row.comment = source[:200]
    row.strategy = source[:80]


def _stops_rejected(broker: dict) -> bool:
    text = f"{broker.get('message') or ''} {broker.get('string_code') or ''}".lower()
    if "invalid stop" in text:
        return True
    try:
        return int(broker.get("numeric_code") or 0) == 10016
    except (TypeError, ValueError):
        return False


def _retry_without_rejected_stop(action, symbol, side, volume, stop, take, limit, source, credentials, broker, auto_stop, auto_target, pip, entry):
    """Widen an automatic stop from 100 pips to 300, then send without a rejected stop if the broker still refuses it."""
    if broker.get("ok") or not _stops_rejected(broker) or (stop is None and take is None):
        return broker, "", None
    connector = MetaApiConnector()
    if auto_stop and pip > 0:
        from app.connectors.synthetic_lots import plan_protection

        wider_stop, wider_take, _, _ = plan_protection(side, entry, None, None if auto_target else take, pip, 300)
        if wider_stop is not None and wider_stop != stop:
            attempt = connector.trade(credentials, _broker_open(action, symbol, side, volume, wider_stop, wider_take, limit, source))
            if attempt.get("ok"):
                target_text = f" Target is 2R at {_plain_lot(wider_take)}." if auto_target and wider_take is not None else ""
                note = f"The 100 pip stop was rejected, so the stop is 300 pips at {_plain_lot(wider_stop)}.{target_text}"
                return attempt, note, None
            broker = attempt
            stop, take = wider_stop, wider_take
    if broker.get("ok") or not _stops_rejected(broker):
        return broker, "", None
    candidates = []
    if stop is not None:
        candidates.append((None, take, stop))
    if stop is not None and take is not None:
        candidates.append((stop, None, None))
    candidates.append((None, None, stop))
    seen = {(stop, take)}
    for next_stop, next_take, naked in candidates:
        if (next_stop, next_take) in seen:
            continue
        seen.add((next_stop, next_take))
        attempt = connector.trade(credentials, _broker_open(action, symbol, side, volume, next_stop, next_take, limit, source))
        if not attempt.get("ok"):
            broker = attempt
            continue
        if naked is not None and next_stop is None:
            note = (
                f"Stop {_plain_lot(naked)} was rejected, so this {side} {symbol} was sent without a stop. "
                "A Telegram reminder will repeat every 5 minutes until a stop is set or the order is deleted."
            )
            return attempt, note, naked
        if next_take is None and take is not None:
            return attempt, f"Target {_plain_lot(take)} was rejected, so this {side} {symbol} was sent without a target.", None
        return attempt, "", None
    return broker, "", None


def _remember_naked_limit(db, account, broker, symbol, side, entry, volume, ignored_stop) -> None:
    from app.models.entities import NakedLimit

    ticket = str(broker.get("order_id") or broker.get("position_id") or "").strip()
    if ticket:
        existing = db.scalar(select(NakedLimit).where(NakedLimit.account_id == account.id, NakedLimit.ticket == ticket))
        if existing is not None:
            return
    db.add(
        NakedLimit(
            organization_id=account.organization_id,
            account_id=account.id,
            ticket=ticket,
            symbol=symbol,
            side=side,
            entry=entry,
            volume=volume,
            ignored_stop=ignored_stop,
        )
    )


def _broker_open(action: str, symbol: str, side: str, volume: Decimal, stop: Decimal | None, take: Decimal | None, limit: Decimal | None, comment: str) -> dict:
    if action == "limit":
        kind = "ORDER_TYPE_BUY_LIMIT" if side == "buy" else "ORDER_TYPE_SELL_LIMIT"
        body: dict = {"actionType": kind, "symbol": symbol, "volume": _num(volume), "openPrice": _num(limit or Decimal("0"))}
    else:
        kind = "ORDER_TYPE_BUY" if side == "buy" else "ORDER_TYPE_SELL"
        body = {"actionType": kind, "symbol": symbol, "volume": _num(volume)}
    if stop is not None:
        body["stopLoss"] = _num(stop)
    if take is not None:
        body["takeProfit"] = _num(take)
    if comment:
        body["comment"] = comment
    return body


def _finish(db, user, account, action, symbol, volume, decision, hits, broker, actor, *, sent: bool, risk_blocks_paused: bool = False, source: str = "") -> dict:
    write_audit(
        db,
        organization_id=account.organization_id,
        actor_user_id=user.id,
        actor_type="ai" if actor == "ai" else "user",
        action="order_submitted",
        entity_type="account",
        entity_id=str(account.id),
        after={
            "action": action,
            "symbol": symbol,
            "volume": "" if volume is None else str(volume),
            "decision": decision,
            "numeric_code": broker.get("numeric_code") or 0,
            "sent": sent,
            "actor": actor,
            "source": source,
            "risk_blocks_paused": risk_blocks_paused,
        },
    )
    message = str(broker.get("message") or "")
    return {
        "sent": sent,
        "decision": decision,
        "hits": hits,
        "numeric_code": broker.get("numeric_code") or 0,
        "message": message,
        "order_id": broker.get("order_id") or "",
        "position_id": broker.get("position_id") or "",
        "risk_blocks_paused": risk_blocks_paused,
    }


def save_trading_contact(db: Session, user: User, account: Account, app_id: str, api_secret: str, bot_token: str) -> dict:
    app_id = app_id.strip()
    api_secret = api_secret.strip()
    bot_token = bot_token.strip()
    if len(app_id) < 4:
        raise OrderError(400, "Enter the app id")
    if len(api_secret) < 8:
        raise OrderError(400, "Enter the API secret")
    if len(bot_token) < 20:
        raise OrderError(400, "Enter a bot token of at least 20 characters")
    digest = sha256_hex(bot_token)
    taken = db.scalar(select(Account.id).where(Account.bot_token_hash == digest, Account.id != account.id))
    if taken is not None:
        raise OrderError(400, "That bot token is already in use")
    region = str(load_credentials(db, account.id).get("region") or "")
    _remember_trading_api(db, account.id, app_id, api_secret, region, bot_token)
    account.bot_token_hash = digest
    write_audit(
        db,
        organization_id=account.organization_id,
        actor_user_id=user.id,
        action="trading_api_saved",
        entity_type="account",
        entity_id=str(account.id),
        after={"app_id": app_id, "bot_token_set": True},
    )
    return {"saved": True, "bot_token_set": True}


def close_with_bot_token(db: Session, token: str) -> dict:
    token = token.strip()
    if not token:
        raise OrderError(401, "Send the bot token")
    account = db.scalar(select(Account).where(Account.bot_token_hash == sha256_hex(token)))
    if account is None:
        raise OrderError(401, "Bot token was not recognized")
    saved = load_credentials(db, account.id)
    app_id = str(saved.get("trading_app_id") or "")
    api_secret = str(saved.get("trading_api_key") or "")
    if not app_id or not api_secret:
        raise OrderError(400, "Save the app id and API secret first")
    return close_ai_trading(db, None, account, app_id, api_secret)


def close_ai_trading(db: Session, user: User | None, account: Account, app_id: str, api_key: str) -> dict:
    if account.connection_method != "metaapi":
        raise OrderError(400, "This connection cannot close trades")
    app_id = app_id.strip()
    api_key = api_key.strip()
    if not app_id or not api_key:
        raise OrderError(400, "Enter the app id and API secret")
    connector = MetaApiConnector()
    probe = connector.inspect({"token": api_key, "metaapi_account_id": app_id})
    if not probe.get("ok"):
        raise OrderError(400, _trading_api_detail(probe))
    login = str((probe.get("account") or {}).get("account_number") or "").strip()
    if not login or login != str(account.account_number).strip():
        raise OrderError(400, "That app id belongs to a different account")
    region = str(probe.get("region") or "")
    credentials = {"token": api_key, "metaapi_account_id": app_id, "region": region}
    try:
        positions = connector.fetch_positions(credentials)
    except Exception as exc:  # noqa: BLE001
        raise OrderError(502, "Trading API did not return open trades") from exc
    closed: list[str] = []
    failed: list[dict] = []
    for position in positions:
        result = connector.trade(credentials, {"actionType": "POSITION_CLOSE_ID", "positionId": position.ticket})
        if result.get("ok"):
            closed.append(position.ticket)
        else:
            failed.append({"ticket": position.ticket, "message": str(result.get("message") or "close failed")[:240]})
    account.ai_trading_enabled = False
    _remember_trading_api(db, account.id, app_id, api_key, region)
    write_audit(
        db,
        organization_id=account.organization_id,
        actor_user_id=None if user is None else user.id,
        actor_type="user" if user is not None else "service",
        action="ai_trading_closed",
        entity_type="account",
        entity_id=str(account.id),
        after={"ai_trading_enabled": False, "closed_tickets": closed, "failed_count": len(failed), "app_id": app_id},
    )
    return {"ai_trading_enabled": False, "closed_tickets": closed, "failed": failed}


def _trading_api_detail(probe: dict) -> str:
    code = str(probe.get("error_code") or "")
    if code == "metaapi_account_id":
        return "Enter the trading API app id"
    if code == "metaapi_unauthorized":
        return "The trading API rejected that API secret"
    return str(probe.get("detail") or "Trading API rejected the app id or API key")


def _remember_trading_api(db: Session, account_id, app_id: str, api_key: str, region: str, bot_token: str = "") -> None:
    current = load_credentials(db, account_id)
    current["trading_app_id"] = app_id
    current["trading_api_key"] = api_key
    if bot_token:
        current["trading_bot_token"] = bot_token
    if region:
        current["trading_region"] = region
    nonce, ciphertext = encrypt_json(current)
    row = db.scalar(select(AccountCredential).where(AccountCredential.account_id == account_id))
    if row is None:
        db.add(AccountCredential(account_id=account_id, nonce=nonce, ciphertext=ciphertext))
        return
    row.nonce = nonce
    row.ciphertext = ciphertext
    row.rotated_at = datetime.now(timezone.utc)


def _decimal(value: object, label: str) -> Decimal:
    if value in (None, ""):
        raise OrderError(400, f"Enter {label}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OrderError(400, f"Enter {label}") from exc
    if not number.is_finite():
        raise OrderError(400, f"Enter {label}")
    return number


def _optional(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    number = _decimal(value, "a price")
    return number


def _num(value: Decimal) -> float:
    return float(value)


def _fit_volume(volume: Decimal, spec: SymbolSpec) -> Decimal:
    step = spec.volume_step if spec.volume_step > 0 else Decimal("0.01")
    minimum = spec.volume_min if spec.volume_min > 0 else step
    fitted = volume if volume > minimum else minimum
    steps = (fitted / step).to_integral_value(rounding=ROUND_CEILING)
    fitted = steps * step
    if fitted < minimum:
        fitted = minimum
    if spec.volume_max > 0 and fitted > spec.volume_max:
        raise OrderError(400, f"Maximum volume for {spec.broker_symbol} is {_plain_lot(spec.volume_max)}")
    return fitted


def _plain_lot(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def account_symbols(db: Session, account: Account) -> list[str]:
    names: list[str] = []
    for query in (
        select(Position.symbol).where(Position.account_id == account.id),
        select(ClosedTrade.symbol).where(ClosedTrade.account_id == account.id),
        select(SymbolSpecRow.broker_symbol).where(SymbolSpecRow.account_id == account.id),
    ):
        for name in db.scalars(query).all():
            text = str(name or "").strip()
            if text and text not in names:
                names.append(text)
    return names


def symbol_guide(known: list[str]) -> str:
    volatility = [name for name in known if "volatility" in name.lower()]
    others = [name for name in known if "volatility" not in name.lower()]
    lines = [
        "On this account VIX means the broker volatility indices, not a ticker named VIX. Never send the symbol VIX.",
        "VIX 75 means Volatility 75 Index. VIX 75 1s means Volatility 75 (1s) Index. Use the same pattern for 10, 15, 25, 30, 50, 90, and 100.",
        "When the user says only VIX or volatility, ask which number they mean and use one of the symbols below.",
    ]
    if volatility:
        lines.append("Volatility symbols on this account: " + ", ".join(volatility[:24]) + ".")
    if others:
        lines.append("Other symbols on this account: " + ", ".join(others[:12]) + ".")
    return " ".join(lines)


def minimum_volume_guide(db: Session, account: Account) -> str:
    rows = db.scalars(select(SymbolSpecRow).where(SymbolSpecRow.account_id == account.id).order_by(SymbolSpecRow.broker_symbol)).all()
    parts = [f"{row.broker_symbol} minimum {_plain_lot(row.volume_min)}" for row in rows if row.volume_min and row.volume_min > 0]
    if not parts:
        return ""
    return " Use at least the symbol minimum volume. " + "; ".join(parts[:24]) + "."


def resolve_broker_symbol(requested: str, known: list[str]) -> str:
    text = requested.strip()
    if not text:
        raise OrderError(400, "Enter a symbol")
    for name in known:
        if name.lower() == text.lower():
            return name
    alias, number, one_second = _volatility_alias(text)
    if not alias:
        return text
    volatility = [name for name in known if "volatility" in name.lower()]
    if number is None:
        if len(volatility) == 1:
            return volatility[0]
        choices = volatility or ["Volatility 75 Index", "Volatility 75 (1s) Index"]
        raise OrderError(400, "VIX means a volatility index. Choose one: " + ", ".join(choices[:12]))
    matches = [name for name in volatility if _index_number(name) == number and _one_second(name) == one_second]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return matches[0]
    speed = " (1s)" if one_second else ""
    return f"Volatility {number}{speed} Index"


def _volatility_alias(text: str) -> tuple[bool, str | None, bool]:
    lowered = text.lower()
    one_second = bool(re.search(r"\b1\s*s\b", lowered))
    without_speed = re.sub(r"\b1\s*s\b", " ", lowered)
    compact = re.sub(r"[^a-z0-9]+", " ", without_speed).strip()
    alias = bool(re.search(r"\b(vix|volatility|vol)\b", compact))
    numbers = re.findall(r"\d+", compact)
    return alias, (numbers[0] if numbers else None), one_second


def _index_number(symbol: str) -> str | None:
    without_speed = re.sub(r"\(1s\)", " ", symbol.lower())
    numbers = re.findall(r"\d+", without_speed)
    return numbers[0] if numbers else None


def _one_second(symbol: str) -> bool:
    return "(1s)" in symbol.lower()

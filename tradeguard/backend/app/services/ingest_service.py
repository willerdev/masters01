from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tradeguard_risk.decisions import evaluate_fail_closed
from tradeguard_risk.drawdown import current_drawdown_pct, daily_pnl
from tradeguard_risk.overtrading import TradeSample, assess_overtrading
from tradeguard_risk.quotes import quote_is_stale
from tradeguard_risk.sizing import position_risk
from tradeguard_risk.types import AccountRiskState, ControlState, Decision, OpenPosition, ProposedOrder, SymbolSpec

from app.connectors.normalize import NormalizeError, canonical_symbol, normalize_account, normalize_position, normalize_quote
from app.connectors.symbol_catalog import catalog_spec
from app.core.config import get_settings
from app.core.encryption import decrypt_json
from app.domain.audit import write_audit
from app.domain.ruleset import rules_from_rows
from app.models.entities import (
    Account,
    AccountConnection,
    AccountSnapshot,
    AccountState,
    ClosedTrade,
    DailyStatistic,
    DrawdownSnapshot,
    EquitySnapshot,
    MarketQuote,
    OrderRow,
    Position,
    RiskDecisionRow,
    RiskProfile,
    RiskRule,
    RiskViolation,
    SymbolSpecRow,
    WebhookEndpoint,
    WebhookInbox,
    WebhookNonce,
)
from app.services.alert_service import raise_alert

EVENT_TYPES = {
    "ORDER_OPENED",
    "ORDER_CLOSED",
    "ORDER_MODIFIED",
    "POSITION_UPDATED",
    "ACCOUNT_UPDATE",
    "HEARTBEAT",
}

_buckets: dict[str, list[float]] = {}


class WebhookRejected(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def sign_webhook(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = timestamp.encode() + b"." + nonce.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _rate_limit(token: str) -> None:
    now = time.monotonic()
    window = [stamp for stamp in _buckets.get(token, []) if now - stamp < 1]
    if len(window) >= 30:
        raise WebhookRejected(429, "Rate limit exceeded")
    window.append(now)
    _buckets[token] = window


def accept_webhook(
    db: Session,
    *,
    token: str,
    api_key: str,
    timestamp: str,
    nonce: str,
    signature: str,
    body: bytes,
) -> dict:
    if len(body) > 256_000:
        raise WebhookRejected(413, "Payload too large")
    _rate_limit(token)
    endpoint = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.token == token, WebhookEndpoint.enabled.is_(True)))
    if endpoint is None:
        raise WebhookRejected(401, "Webhook unauthorized")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WebhookRejected(401, "Invalid timestamp") from exc
    if abs(int(time.time()) - ts) > get_settings().webhook_skew_seconds:
        raise WebhookRejected(401, "Webhook unauthorized")
    from app.core.security import sha256_hex

    if not api_key or not hmac.compare_digest(sha256_hex(api_key), endpoint.api_key_hash):
        raise WebhookRejected(401, "Webhook unauthorized")
    secret = str(decrypt_json(endpoint.secret_nonce, endpoint.secret_ciphertext).get("secret") or "")
    expected = sign_webhook(secret, timestamp, nonce, body)
    presented = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, presented):
        raise WebhookRejected(401, "Webhook unauthorized")
    if db.get(WebhookNonce, nonce) is not None:
        raise WebhookRejected(401, "Replay detected")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WebhookRejected(400, "Invalid JSON") from exc
    event_id = str(payload.get("event_id") or "").strip()
    event_type = str(payload.get("event_type") or "").strip()
    if not event_id or event_type not in EVENT_TYPES:
        raise WebhookRejected(400, "event_id and a supported event_type are required")
    if not payload.get("occurred_at") and event_type != "HEARTBEAT":
        raise WebhookRejected(400, "occurred_at is required")
    account = db.get(Account, endpoint.account_id)
    if account is None:
        raise WebhookRejected(404, "Account missing")
    claimed = str(payload.get("account_number") or "")
    if claimed and claimed != account.account_number:
        raise WebhookRejected(400, "Account number does not match this webhook")
    existing = db.scalar(
        select(WebhookInbox).where(
            WebhookInbox.endpoint_id == endpoint.id,
            WebhookInbox.external_event_id == event_id,
        )
    )
    if existing:
        return {"duplicate": True, "event_id": event_id, "decision": existing.decision, "status": existing.status}
    db.add(
        WebhookNonce(
            nonce=nonce,
            endpoint_id=endpoint.id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=get_settings().webhook_skew_seconds),
        )
    )
    inbox = WebhookInbox(
        endpoint_id=endpoint.id,
        external_event_id=event_id,
        event_type=event_type,
        payload=payload,
        status="received",
    )
    db.add(inbox)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise WebhookRejected(200, "duplicate") from exc
    decision = process_inbox(db, inbox, account)
    write_audit(
        db,
        organization_id=account.organization_id,
        actor_type="webhook",
        action="webhook_event",
        entity_type="webhook_inbox",
        entity_id=str(inbox.id),
        after={"event_type": event_type, "event_id": event_id, "decision": decision},
    )
    from app.core.telemetry import telemetry

    telemetry.webhooks += 1
    telemetry.decisions[decision] += 1
    return {"duplicate": False, "event_id": event_id, "decision": decision, "status": "processed"}


def process_inbox(db: Session, inbox: WebhookInbox, account: Account) -> str:
    payload = inbox.payload
    event_type = inbox.event_type
    occurred = _parse_time(payload.get("occurred_at")) or datetime.now(timezone.utc)
    data = payload.get("data") or {}
    _maybe_store_spec(db, account, data.get("symbol_spec"), str(data.get("symbol") or ""))
    decision = ""
    if event_type == "HEARTBEAT":
        _heartbeat(db, account, data, occurred)
        decision = "ALLOW"
    elif event_type == "ACCOUNT_UPDATE":
        decision = _account_update(db, account, data, occurred, inbox.external_event_id)
    elif event_type == "ORDER_OPENED":
        decision = _order_opened(db, account, data, occurred, inbox.external_event_id)
    elif event_type == "ORDER_CLOSED":
        decision = _order_closed(db, account, data, occurred, inbox.external_event_id)
    elif event_type in {"ORDER_MODIFIED", "POSITION_UPDATED"}:
        decision = _position_updated(db, account, data, occurred, inbox.external_event_id)
    inbox.status = "processed"
    inbox.decision = decision
    inbox.processed_at = datetime.now(timezone.utc)
    _refresh_overtrading(db, account, occurred)
    return decision


def _heartbeat(db: Session, account: Account, data: dict, occurred: datetime) -> None:
    connection = _connection(db, account)
    connection.last_heartbeat_at = occurred
    connection.last_success_at = occurred
    connection.status = "connected"
    connection.last_error_code = ""
    account.status = "connected"
    account.last_sync_at = occurred
    if any(key in data for key in ("balance", "equity")):
        _apply_account_numbers(db, account, data, occurred, source="heartbeat")


def _account_update(db: Session, account: Account, data: dict, occurred: datetime, event_id: str) -> str:
    try:
        normalized = normalize_account(data)
    except NormalizeError as exc:
        raise WebhookRejected(400, str(exc)) from exc
    _apply_account_numbers(
        db,
        account,
        {
            "balance": normalized.balance,
            "equity": normalized.equity,
            "margin": normalized.margin,
            "free_margin": normalized.free_margin,
            "margin_level": normalized.margin_level,
        },
        occurred,
        source="account_update",
    )
    account.status = "connected"
    account.last_sync_at = occurred
    _connection(db, account).last_heartbeat_at = occurred
    _connection(db, account).status = "connected"
    result = _evaluate(db, account, occurred, event_id, proposed=None)
    return result.decision.value


def _order_opened(db: Session, account: Account, data: dict, occurred: datetime, event_id: str) -> str:
    try:
        position = normalize_position(data, str(account.id))
    except NormalizeError as exc:
        raise WebhookRejected(400, str(exc)) from exc
    if position.open_time is None:
        position.open_time = occurred
    _upsert_position(db, account, position)
    _touch_quote(db, account, position.symbol, position.current_price, occurred, "mt5")
    spec = _spec_for(db, account, position.symbol)
    fx = _fx(account, spec)
    proposed = ProposedOrder(
        position.symbol,
        position.side,
        position.volume,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
        position.ticket,
    )
    result = _evaluate(db, account, occurred, event_id, proposed=proposed, spec=spec, fx=fx)
    _store_position_risk(db, account.id, position.ticket, result.risk_amount, result.risk_percent)
    _bump_trade_count(db, account, occurred)
    if result.decision in {Decision.BLOCK, Decision.EMERGENCY_STOP}:
        from app.models.entities import BrokerCommand

        db.add(
            BrokerCommand(
                account_id=account.id,
                command="DISABLE_NEW_TRADES" if result.decision == Decision.BLOCK else "EMERGENCY_STOP",
                detail={"ticket": position.ticket, "decision": result.decision.value},
            )
        )
    if result.decision in {Decision.ALLOW, Decision.WARNING}:
        from app.services.copy_service import propagate_open

        propagate_open(db, account, position, event_id)
    return result.decision.value


def _order_closed(db: Session, account: Account, data: dict, occurred: datetime, event_id: str) -> str:
    ticket = str(data.get("ticket") or data.get("position_id") or "")
    position = db.scalar(select(Position).where(Position.account_id == account.id, Position.ticket == ticket, Position.status == "open"))
    profit = Decimal(str(data.get("profit", position.profit if position else "0")))
    close_price = Decimal(str(data.get("close_price") or data.get("price") or (position.current_price if position else "0")))
    if position:
        db.add(
            ClosedTrade(
                account_id=account.id,
                ticket=position.ticket,
                symbol=position.symbol,
                side=position.side,
                volume=position.volume,
                entry_price=position.entry_price,
                close_price=close_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                profit=profit,
                swap=position.swap,
                commission=position.commission,
                risk_amount=position.risk_amount,
                risk_percent=position.risk_percent,
                open_time=position.open_time,
                close_time=occurred,
                magic_number=position.magic_number,
                comment=position.comment,
                strategy=position.strategy or position.comment,
            )
        )
        position.status = "closed"
        position.current_price = close_price
        position.profit = profit
    if "equity" in data or "balance" in data:
        _apply_account_numbers(db, account, data, occurred, source="close")
    result = _evaluate(db, account, occurred, event_id, proposed=None)
    return result.decision.value


def _position_updated(db: Session, account: Account, data: dict, occurred: datetime, event_id: str) -> str:
    try:
        incoming = normalize_position(data, str(account.id))
    except NormalizeError as exc:
        raise WebhookRejected(400, str(exc)) from exc
    _upsert_position(db, account, incoming)
    _touch_quote(db, account, incoming.symbol, incoming.current_price, occurred, "mt5")
    order = db.scalar(select(OrderRow).where(OrderRow.account_id == account.id, OrderRow.ticket == incoming.ticket))
    if order is None:
        db.add(
            OrderRow(
                account_id=account.id,
                ticket=incoming.ticket,
                symbol=incoming.symbol,
                side=incoming.side,
                volume=incoming.volume,
                price=incoming.entry_price,
                stop_loss=incoming.stop_loss,
                take_profit=incoming.take_profit,
                placed_at=incoming.open_time,
            )
        )
    else:
        order.stop_loss = incoming.stop_loss
        order.take_profit = incoming.take_profit
        order.price = incoming.entry_price
        order.updated_at = occurred
    result = _evaluate(db, account, occurred, event_id, proposed=None)
    return result.decision.value


def _evaluate(db, account: Account, now: datetime, event_id: str, proposed: ProposedOrder | None, spec: SymbolSpec | None = None, fx: Decimal = Decimal("1")):
    state_row = _state(db, account)
    rules = rules_from_rows(_rule_rows(db, account))
    positions = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    # A proposed order is not yet in the book when we count; evaluate_proposed adds it.
    if proposed is not None:
        positions = [row for row in positions if row.ticket != proposed.ticket]
    open_positions = tuple(_to_open(row) for row in positions)
    specs = {row.symbol: _spec_for(db, account, row.symbol) for row in positions}
    if spec is not None and proposed is not None:
        specs[proposed.symbol] = spec
    fx_rates = {item.profit_currency: _fx(account, item) for item in specs.values()}
    quote_time = db.scalar(select(func.max(MarketQuote.captured_at)).where(MarketQuote.account_id == account.id))
    stale = quote_is_stale(quote_time, now, get_settings().stale_quote_seconds) if positions or proposed else False
    risk_state = AccountRiskState(
        equity=state_row.equity or Decimal("0"),
        balance=state_row.balance or Decimal("0"),
        margin=state_row.margin or Decimal("0"),
        free_margin=state_row.free_margin or Decimal("0"),
        margin_level=state_row.margin_level,
        day_start_equity=state_row.day_start_equity or state_row.equity or Decimal("0"),
        peak_equity=state_row.peak_equity or state_row.equity or Decimal("0"),
        trades_today=_trades_today(db, account, now),
        consecutive_losses=_loss_streak(db, account.id),
        open_positions=open_positions,
        last_entry_at=_last_entry(db, account.id, None if proposed is None else proposed.ticket),
        control_state=ControlState(account.control_state),
        currency=account.currency,
        exposure_account=_exposure(positions),
    )
    result = evaluate_fail_closed(
        risk_state,
        rules,
        order=proposed,
        spec=spec,
        fx_to_account=fx,
        specs=specs,
        fx_rates=fx_rates,
        now=now,
        stale_input=stale,
    )
    decision_row = RiskDecisionRow(
        account_id=account.id,
        source_event_id=event_id,
        decision=result.decision.value,
        hits=[
            {"code": hit.code, "decision": hit.decision.value, "observed": hit.observed, "limit": hit.limit, "message": hit.message}
            for hit in result.hits
        ],
        risk_amount=result.risk_amount,
        risk_percent=result.risk_percent,
        open_risk_amount=result.open_risk_amount,
        daily_loss_percent=result.daily_loss_percent,
        drawdown_percent=result.drawdown_percent,
        stale_input=result.stale_input,
    )
    db.add(decision_row)
    db.flush()
    if account.monitoring_enabled:
        _sync_violations(db, account, decision_row, result)
    write_audit(
        db,
        organization_id=account.organization_id,
        actor_type="risk_engine",
        action="risk_decision",
        entity_type="risk_decision",
        entity_id=str(decision_row.id),
        after={"decision": result.decision.value, "event_id": event_id, "stale": result.stale_input},
    )
    return result


def _sync_violations(db, account: Account, decision_row: RiskDecisionRow, result) -> None:
    for hit in result.hits:
        if hit.decision == Decision.ALLOW:
            continue
        db.add(
            RiskViolation(
                account_id=account.id,
                decision_id=decision_row.id,
                code=hit.code,
                severity=hit.decision.value,
                observed_value=hit.observed,
                limit_value=hit.limit,
                message=hit.message,
            )
        )
        raise_alert(
            db,
            organization_id=account.organization_id,
            account_id=account.id,
            alert_type=hit.code.lower(),
            severity=hit.decision.value,
            title=f"{hit.code.replace('_', ' ').title()} on {account.display_name}",
            body=hit.message,
            dedupe_key=f"{account.id}:{hit.code}:{hit.decision.value}",
        )


def _apply_account_numbers(db, account: Account, data: dict, occurred: datetime, source: str) -> None:
    state = _state(db, account)
    balance = Decimal(str(data.get("balance", state.balance or 0)))
    equity = Decimal(str(data.get("equity", state.equity or 0)))
    today = _trading_date(account, occurred)
    if state.trading_date != today:
        state.day_start_equity = equity
        state.trading_date = today
    if state.peak_equity is None or equity > state.peak_equity:
        state.peak_equity = equity
    state.balance = balance
    state.equity = equity
    state.margin = Decimal(str(data.get("margin", state.margin or 0)))
    state.free_margin = Decimal(str(data.get("free_margin", state.free_margin or 0)))
    if data.get("margin_level") is not None:
        state.margin_level = Decimal(str(data["margin_level"]))
    state.as_of = occurred
    state.stale = False
    snapshot = db.scalar(select(AccountSnapshot).where(AccountSnapshot.account_id == account.id, AccountSnapshot.captured_at == occurred))
    if snapshot is None:
        snapshot = AccountSnapshot(account_id=account.id, captured_at=occurred, balance=balance, equity=equity, source=source)
        db.add(snapshot)
    snapshot.balance = balance
    snapshot.equity = equity
    snapshot.margin = state.margin
    snapshot.free_margin = state.free_margin
    snapshot.margin_level = state.margin_level
    snapshot.source = source
    equity_row = db.scalar(select(EquitySnapshot).where(EquitySnapshot.account_id == account.id, EquitySnapshot.captured_at == occurred))
    if equity_row is None:
        equity_row = EquitySnapshot(account_id=account.id, captured_at=occurred, equity=equity, balance=balance)
        db.add(equity_row)
    equity_row.equity = equity
    equity_row.balance = balance
    peak = state.peak_equity or equity
    dd = current_drawdown_pct(peak, equity)
    drawdown_row = db.scalar(select(DrawdownSnapshot).where(DrawdownSnapshot.account_id == account.id, DrawdownSnapshot.captured_at == occurred))
    if drawdown_row is None:
        drawdown_row = DrawdownSnapshot(
            account_id=account.id,
            captured_at=occurred,
            equity=equity,
            peak_equity=peak,
            drawdown_abs=max(peak - equity, Decimal("0")),
            drawdown_pct=dd,
        )
        db.add(drawdown_row)
    drawdown_row.equity = equity
    drawdown_row.peak_equity = peak
    drawdown_row.drawdown_abs = max(peak - equity, Decimal("0"))
    drawdown_row.drawdown_pct = dd
    stat = _daily(db, account, today, equity)
    stat.end_equity = equity
    stat.realized_pnl = daily_pnl(stat.start_equity, equity)


def _upsert_position(db, account: Account, position) -> None:
    row = db.scalar(select(Position).where(Position.account_id == account.id, Position.ticket == position.ticket))
    if row is None:
        row = Position(account_id=account.id, ticket=position.ticket, status="open")
        db.add(row)
    row.symbol = position.symbol
    row.side = position.side
    row.volume = position.volume
    row.entry_price = position.entry_price
    row.current_price = position.current_price or position.entry_price
    row.stop_loss = position.stop_loss
    row.take_profit = position.take_profit
    row.profit = position.profit
    row.swap = position.swap
    row.commission = position.commission
    row.open_time = position.open_time
    row.magic_number = position.magic_number
    incoming_comment = str(position.comment or "").strip()
    if incoming_comment:
        row.comment = incoming_comment[:200]
        row.strategy = incoming_comment[:80]
    elif not row.comment:
        row.comment = ""
        row.strategy = ""
    row.status = "open"
    row.updated_at = datetime.now(timezone.utc)


def _store_position_risk(db, account_id, ticket: str, amount, percent) -> None:
    row = db.scalar(select(Position).where(Position.account_id == account_id, Position.ticket == ticket))
    if row:
        row.risk_amount = amount
        row.risk_percent = percent


def _maybe_store_spec(db, account: Account, raw: object, symbol: str) -> None:
    if not isinstance(raw, dict) or not symbol:
        return
    try:
        tick_size = Decimal(str(raw["tick_size"]))
        tick_value = Decimal(str(raw["tick_value"]))
        contract_size = Decimal(str(raw["contract_size"]))
        volume_step = Decimal(str(raw["volume_step"]))
    except (KeyError, ValueError):
        return
    row = db.scalar(select(SymbolSpecRow).where(SymbolSpecRow.account_id == account.id, SymbolSpecRow.broker_symbol == symbol))
    if row is None:
        row = SymbolSpecRow(account_id=account.id, broker_symbol=symbol, tick_size=tick_size, tick_value=tick_value, contract_size=contract_size, volume_min=Decimal("0.01"), volume_max=Decimal("100"), volume_step=volume_step)
        db.add(row)
    row.tick_size = tick_size
    row.tick_value = tick_value
    row.contract_size = contract_size
    row.volume_min = Decimal(str(raw.get("volume_min", row.volume_min)))
    row.volume_max = Decimal(str(raw.get("volume_max", row.volume_max)))
    row.volume_step = volume_step
    row.profit_currency = str(raw.get("profit_currency") or account.currency)
    row.digits = int(raw.get("digits") or 5)
    row.calc_mode = str(raw.get("calc_mode") or "forex")
    row.asset_class = str(raw.get("asset_class") or "forex")
    row.canonical_symbol = canonical_symbol(symbol)
    row.confidence = "exact"


def _spec_for(db, account: Account, symbol: str) -> SymbolSpec:
    row = db.scalar(select(SymbolSpecRow).where(SymbolSpecRow.account_id == account.id, SymbolSpecRow.broker_symbol == symbol))
    if row:
        return SymbolSpec(
            broker_symbol=row.broker_symbol,
            tick_size=row.tick_size,
            tick_value=row.tick_value,
            contract_size=row.contract_size,
            volume_min=row.volume_min,
            volume_max=row.volume_max,
            volume_step=row.volume_step,
            profit_currency=row.profit_currency,
            digits=row.digits,
            asset_class=row.asset_class,
            calc_mode=row.calc_mode,
        )
    catalog = catalog_spec(symbol)
    if catalog:
        return catalog
    return SymbolSpec(symbol, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), account.currency)


def _fx(account: Account, spec: SymbolSpec) -> Decimal:
    if spec.profit_currency.upper() == account.currency.upper():
        return Decimal("1")
    return Decimal("0")


def _state(db, account: Account) -> AccountState:
    state = db.get(AccountState, account.id)
    if state is None:
        state = AccountState(account_id=account.id)
        db.add(state)
        db.flush()
    return state


def _connection(db, account: Account) -> AccountConnection:
    connection = db.scalar(select(AccountConnection).where(AccountConnection.account_id == account.id))
    if connection is None:
        connection = AccountConnection(account_id=account.id, method=account.connection_method)
        db.add(connection)
        db.flush()
    return connection


def _rule_rows(db, account: Account) -> list[RiskRule]:
    profile = db.scalar(select(RiskProfile).where(RiskProfile.account_id == account.id))
    if profile is None:
        profile = db.scalar(
            select(RiskProfile).where(RiskProfile.organization_id == account.organization_id, RiskProfile.is_default.is_(True))
        )
    if profile is None:
        return []
    return list(db.scalars(select(RiskRule).where(RiskRule.profile_id == profile.id)).all())


def _to_open(row: Position) -> OpenPosition:
    return OpenPosition(
        ticket=row.ticket,
        symbol=row.symbol,
        side=row.side,
        volume=row.volume,
        entry_price=row.entry_price,
        current_price=row.current_price,
        stop_loss=row.stop_loss,
        profit=row.profit,
        open_time=row.open_time,
        take_profit=row.take_profit,
    )


def _trading_date(account: Account, moment: datetime):
    try:
        tz = ZoneInfo(account.trading_day_timezone or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).date()


def _daily(db, account: Account, trading_date, equity: Decimal) -> DailyStatistic:
    stat = db.scalar(select(DailyStatistic).where(DailyStatistic.account_id == account.id, DailyStatistic.trading_date == trading_date))
    if stat is None:
        stat = DailyStatistic(account_id=account.id, trading_date=trading_date, start_equity=equity, end_equity=equity)
        db.add(stat)
        db.flush()
    return stat


def _bump_trade_count(db, account: Account, moment: datetime) -> None:
    state = _state(db, account)
    stat = _daily(db, account, _trading_date(account, moment), state.equity or Decimal("0"))
    stat.trade_count += 1


def _trades_today(db, account: Account, moment: datetime) -> int:
    stat = db.scalar(
        select(DailyStatistic).where(
            DailyStatistic.account_id == account.id,
            DailyStatistic.trading_date == _trading_date(account, moment),
        )
    )
    return stat.trade_count if stat else 0


def _loss_streak(db, account_id) -> int:
    rows = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account_id).order_by(ClosedTrade.close_time.desc())).all()
    streak = 0
    for row in rows:
        if row.profit < 0:
            streak += 1
        else:
            break
    return streak


def _last_entry(db, account_id, exclude_ticket: str | None = None):
    query = select(func.max(Position.open_time)).where(Position.account_id == account_id)
    if exclude_ticket:
        query = query.where(Position.ticket != exclude_ticket)
    return db.scalar(query)


def _exposure(positions: list[Position]) -> Decimal:
    total = Decimal("0")
    for row in positions:
        total += abs(row.volume * row.current_price)
    return total


def _touch_quote(db, account: Account, symbol: str, price: Decimal, moment: datetime, source: str) -> None:
    if price <= 0:
        return
    db.add(
        MarketQuote(
            account_id=account.id,
            symbol=symbol,
            bid=price,
            ask=price,
            spread=Decimal("0"),
            source=source,
            captured_at=moment,
            stale=False,
        )
    )
    db.flush()


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _refresh_overtrading(db, account: Account, now: datetime) -> None:
    from app.models.entities import OvertradingRow

    samples: list[TradeSample] = []
    for row in db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account.id)).all():
        if row.open_time:
            samples.append(TradeSample(row.symbol, row.volume, row.open_time, row.close_time, row.profit, abs(row.volume * row.entry_price)))
    for row in db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all():
        if row.open_time:
            samples.append(TradeSample(row.symbol, row.volume, row.open_time, None, row.profit, abs(row.volume * row.current_price)))
    assessment = assess_overtrading(samples, now)
    metrics = assessment.metrics
    db.add(
        OvertradingRow(
            account_id=account.id,
            state=assessment.state.value,
            metrics={
                "trades_per_hour": str(metrics.trades_per_hour),
                "trades_per_day": metrics.trades_per_day,
                "average_holding_seconds": None if metrics.average_holding_seconds is None else str(metrics.average_holding_seconds),
                "average_seconds_between_trades": None if metrics.average_seconds_between_trades is None else str(metrics.average_seconds_between_trades),
                "trades_after_losses": metrics.trades_after_losses,
                "lot_escalation": None if metrics.lot_escalation is None else str(metrics.lot_escalation),
                "loss_streak": metrics.loss_streak,
                "symbol_concentration": str(metrics.symbol_concentration),
                "exposure_concentration": str(metrics.exposure_concentration),
                "rapid_reentry_count": metrics.rapid_reentry_count,
            },
            bands=assessment.bands,
        )
    )
    if assessment.state.value in {"HIGH", "CRITICAL"} and account.monitoring_enabled:
        raise_alert(
            db,
            organization_id=account.organization_id,
            account_id=account.id,
            alert_type="overtrading",
            severity=assessment.state.value,
            title=f"Overtrading {assessment.state.value} on {account.display_name}",
            body="Measured trading frequency and loss-recovery behavior crossed the configured bands.",
            dedupe_key=f"{account.id}:overtrading:{assessment.state.value}",
        )


def sweep_heartbeats(db: Session) -> int:
    timeout = get_settings().heartbeat_timeout_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)
    rows = db.scalars(select(AccountConnection).where(AccountConnection.status == "connected", AccountConnection.method == "webhook")).all()
    changed = 0
    for connection in rows:
        if connection.last_heartbeat_at and connection.last_heartbeat_at >= cutoff:
            continue
        connection.status = "disconnected"
        account = db.get(Account, connection.account_id)
        if account is None:
            continue
        account.status = "disconnected"
        changed += 1
        if account.monitoring_enabled:
            raise_alert(
                db,
                organization_id=account.organization_id,
                account_id=account.id,
                alert_type="account_disconnected",
                severity="WARNING",
                title=f"{account.display_name} disconnected",
                body="The account missed its heartbeat window.",
                dedupe_key=f"{account.id}:disconnected",
            )
            write_audit(
                db,
                organization_id=account.organization_id,
                actor_type="system",
                action="account_disconnected",
                entity_type="account",
                entity_id=str(account.id),
            )
    return changed


def price_position_risk(volume: Decimal, entry: Decimal, stop: Decimal | None, spec: SymbolSpec, equity: Decimal, fx: Decimal):
    return position_risk(ProposedOrder("X", "buy", volume, entry, stop), spec, equity, fx)

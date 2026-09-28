from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from tradeguard_risk.drawdown import current_drawdown_pct, daily_loss_pct
from tradeguard_risk.money import D, quantize_money
from tradeguard_risk.sizing import position_risk
from tradeguard_risk.types import (
    DECISION_RANK,
    AccountRiskState,
    ControlState,
    Decision,
    EffectiveRules,
    OpenPosition,
    ProposedOrder,
    RiskResult,
    RuleHit,
    SymbolSpec,
)


def _rule_on(rules: EffectiveRules, code: str) -> bool:
    return code not in rules.disabled


def _hit(code: str, decision: Decision, observed: object, limit: object, message: str) -> RuleHit:
    return RuleHit(code, decision, str(observed), str(limit), message)


def _strongest(hits: list[RuleHit]) -> Decision:
    if not hits:
        return Decision.ALLOW
    return max(hits, key=lambda hit: DECISION_RANK[hit.decision]).decision


def _utilization_decision(
    observed: Decimal,
    limit: Decimal,
    warning_ratio: Decimal,
    breach: Decision,
    *,
    inclusive: bool,
) -> Decision | None:
    """inclusive=True breaches when observed >= limit (loss, drawdown).

    inclusive=False breaches when observed > limit, so the configured maximum
    itself is still permitted (risk percent, lot, trade counts).
    """
    if limit < 0:
        return None
    breached = observed >= limit if inclusive else observed > limit
    if breached:
        return breach
    if limit > 0 and observed >= limit * warning_ratio:
        return Decision.WARNING
    return None


def _open_risk(state: AccountRiskState, specs: dict[str, SymbolSpec], fx_rates: dict[str, Decimal]) -> tuple[Decimal, list[RuleHit]]:
    total = Decimal("0")
    hits: list[RuleHit] = []
    for position in state.open_positions:
        spec = specs.get(position.symbol)
        if spec is None or position.stop_loss is None:
            hits.append(
                _hit(
                    "UNPROTECTED_POSITION",
                    Decision.WARNING,
                    position.ticket,
                    "stop_loss",
                    f"Position {position.ticket} has no usable stop for risk",
                )
            )
            continue
        order = ProposedOrder(
            symbol=position.symbol,
            side=position.side,
            volume=position.volume,
            entry_price=position.entry_price,
            stop_loss=position.stop_loss,
        )
        fx = fx_rates.get(spec.profit_currency, Decimal("1"))
        sized = position_risk(order, spec, state.equity, fx)
        if sized.incomplete or sized.risk_amount is None:
            hits.append(
                _hit(
                    "INCOMPLETE_SPEC",
                    Decision.WARNING,
                    position.symbol,
                    "symbol_spec",
                    f"Cannot price risk for {position.symbol}",
                )
            )
            continue
        total += sized.risk_amount
    return quantize_money(total), hits


def _portfolio_hits(
    state: AccountRiskState,
    rules: EffectiveRules,
    now: datetime,
    *,
    for_new_trade: bool,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    warn = rules.warning_utilization

    if state.control_state == ControlState.EMERGENCY_STOP:
        hits.append(_hit("ACCOUNT_EMERGENCY_STOP", Decision.EMERGENCY_STOP, state.control_state.value, "ACTIVE", "Account is in emergency stop"))
    elif for_new_trade and state.control_state == ControlState.PAUSED:
        hits.append(_hit("ACCOUNT_PAUSED", Decision.BLOCK, state.control_state.value, "ACTIVE", "Account is paused"))
    elif for_new_trade and state.control_state == ControlState.NEW_TRADES_DISABLED:
        hits.append(_hit("NEW_TRADES_DISABLED", Decision.BLOCK, state.control_state.value, "ACTIVE", "New trades are disabled"))
    elif state.control_state == ControlState.PAUSED:
        hits.append(_hit("ACCOUNT_PAUSED", Decision.WARNING, state.control_state.value, "ACTIVE", "Account is paused"))
    elif state.control_state == ControlState.NEW_TRADES_DISABLED:
        hits.append(_hit("NEW_TRADES_DISABLED", Decision.WARNING, state.control_state.value, "ACTIVE", "New trades are disabled"))

    if _rule_on(rules, "ALLOW_TRADING") and not rules.allow_trading:
        hits.append(
            _hit(
                "TRADING_DISABLED",
                Decision.BLOCK if for_new_trade else Decision.WARNING,
                "off",
                "on",
                "Trading is turned off in the risk profile",
            )
        )

    loss = daily_loss_pct(state.day_start_equity, state.equity)
    loss_decision = (
        _utilization_decision(loss, rules.max_daily_loss_pct, warn, Decision.EMERGENCY_STOP, inclusive=True)
        if _rule_on(rules, "MAX_DAILY_LOSS_PCT")
        else None
    )
    if loss_decision:
        hits.append(
            _hit(
                "MAX_DAILY_LOSS",
                loss_decision,
                f"{loss}",
                f"{rules.max_daily_loss_pct}",
                "Daily loss utilization",
            )
        )

    drawdown = current_drawdown_pct(state.peak_equity, state.equity)
    dd_decision = (
        _utilization_decision(drawdown, rules.max_total_drawdown_pct, warn, Decision.EMERGENCY_STOP, inclusive=True)
        if _rule_on(rules, "MAX_TOTAL_DRAWDOWN_PCT")
        else None
    )
    if dd_decision:
        hits.append(
            _hit(
                "MAX_DRAWDOWN",
                dd_decision,
                f"{drawdown}",
                f"{rules.max_total_drawdown_pct}",
                "Drawdown from peak equity",
            )
        )

    trades = Decimal(state.trades_today)
    trade_decision = (
        _utilization_decision(trades, Decimal(rules.max_trades_per_day), warn, Decision.BLOCK, inclusive=False)
        if _rule_on(rules, "MAX_TRADES_PER_DAY")
        else None
    )
    if trade_decision:
        hits.append(
            _hit(
                "MAX_TRADES_PER_DAY",
                trade_decision,
                str(state.trades_today),
                str(rules.max_trades_per_day),
                "Entries in the trading day",
            )
        )

    open_count = Decimal(len(state.open_positions))
    open_decision = (
        _utilization_decision(open_count, Decimal(rules.max_open_positions), warn, Decision.BLOCK, inclusive=False)
        if _rule_on(rules, "MAX_OPEN_POSITIONS")
        else None
    )
    if open_decision:
        hits.append(
            _hit(
                "MAX_OPEN_POSITIONS",
                open_decision,
                str(len(state.open_positions)),
                str(rules.max_open_positions),
                "Simultaneous open positions",
            )
        )

    if _rule_on(rules, "MAX_CONSECUTIVE_LOSSES") and state.consecutive_losses >= rules.max_consecutive_losses:
        hits.append(
            _hit(
                "MAX_CONSECUTIVE_LOSSES",
                Decision.BLOCK,
                str(state.consecutive_losses),
                str(rules.max_consecutive_losses),
                "Consecutive losing closes",
            )
        )
    elif _rule_on(rules, "MAX_CONSECUTIVE_LOSSES") and rules.max_consecutive_losses > 0 and state.consecutive_losses >= int(rules.max_consecutive_losses * warn):
        hits.append(
            _hit(
                "MAX_CONSECUTIVE_LOSSES",
                Decision.WARNING,
                str(state.consecutive_losses),
                str(rules.max_consecutive_losses),
                "Consecutive losses approaching the limit",
            )
        )

    if _rule_on(rules, "MIN_MINUTES_BETWEEN_TRADES") and for_new_trade and state.last_entry_at is not None and rules.min_minutes_between_trades > 0:
        elapsed = now - state.last_entry_at
        minimum = timedelta(minutes=rules.min_minutes_between_trades)
        if elapsed < minimum:
            hits.append(
                _hit(
                    "MIN_TIME_BETWEEN_TRADES",
                    Decision.BLOCK,
                    str(int(elapsed.total_seconds())),
                    str(rules.min_minutes_between_trades * 60),
                    "Minimum time between entries",
                )
            )

    if state.margin > 0 and state.margin_level is not None:
        if state.margin_level <= rules.margin_level_danger:
            hits.append(
                _hit(
                    "MARGIN_LEVEL_DANGER",
                    Decision.EMERGENCY_STOP,
                    f"{state.margin_level}",
                    f"{rules.margin_level_danger}",
                    "Margin level is at the danger floor",
                )
            )
        elif state.margin_level <= rules.margin_level_warning:
            hits.append(
                _hit(
                    "MARGIN_LEVEL_WARNING",
                    Decision.WARNING,
                    f"{state.margin_level}",
                    f"{rules.margin_level_warning}",
                    "Margin level is elevated",
                )
            )

    if _rule_on(rules, "MAX_EXPOSURE_PCT") and rules.max_exposure_pct is not None and state.equity > 0:
        exposure_pct = state.exposure_account / state.equity * Decimal("100")
        exposure_decision = _utilization_decision(exposure_pct, rules.max_exposure_pct, warn, Decision.BLOCK, inclusive=False)
        if exposure_decision:
            hits.append(
                _hit(
                    "MAX_EXPOSURE",
                    exposure_decision,
                    f"{quantize_money(exposure_pct)}",
                    f"{rules.max_exposure_pct}",
                    "Notional exposure versus equity",
                )
            )
    return hits


def _base_result(state: AccountRiskState, hits: list[RuleHit], open_risk: Decimal, stale_input: bool) -> RiskResult:
    loss = daily_loss_pct(state.day_start_equity, state.equity)
    drawdown = current_drawdown_pct(state.peak_equity, state.equity)
    open_pct = None
    if state.equity > 0:
        open_pct = quantize_money(open_risk / state.equity * Decimal("100"))
    return RiskResult(
        decision=_strongest(hits),
        hits=hits,
        open_risk_amount=open_risk,
        open_risk_percent=open_pct,
        daily_loss_percent=loss,
        drawdown_percent=drawdown,
        stale_input=stale_input,
    )


def evaluate_account(
    state: AccountRiskState,
    rules: EffectiveRules,
    specs: dict[str, SymbolSpec] | None = None,
    fx_rates: dict[str, Decimal] | None = None,
    now: datetime | None = None,
    stale_input: bool = False,
) -> RiskResult:
    specs = specs or {}
    fx_rates = fx_rates or {}
    now = now or datetime.now().astimezone()
    hits = _portfolio_hits(state, rules, now, for_new_trade=False)
    open_risk, risk_hits = _open_risk(state, specs, fx_rates)
    hits.extend(risk_hits)
    if stale_input:
        hits.append(_hit("STALE_MARKET_DATA", Decision.WARNING, "stale", "fresh", "Market data is stale"))
    if _rule_on(rules, "RISK_PER_TRADE_PCT") and state.equity > 0 and rules.risk_per_trade_pct > 0:
        # Portfolio open risk above the per-trade budget is a warning, not a new-order block by itself.
        open_pct = open_risk / state.equity * Decimal("100")
        if open_pct > rules.risk_per_trade_pct * Decimal(max(len(state.open_positions), 1)):
            hits.append(
                _hit(
                    "OPEN_RISK_ELEVATED",
                    Decision.WARNING,
                    f"{quantize_money(open_pct)}",
                    f"{rules.risk_per_trade_pct}",
                    "Aggregate open risk is above the per-trade budget",
                )
            )
    return _base_result(state, hits, open_risk, stale_input)


def evaluate_proposed(
    state: AccountRiskState,
    rules: EffectiveRules,
    order: ProposedOrder,
    spec: SymbolSpec,
    fx_to_account: Decimal = Decimal("1"),
    specs: dict[str, SymbolSpec] | None = None,
    fx_rates: dict[str, Decimal] | None = None,
    now: datetime | None = None,
    stale_input: bool = False,
) -> RiskResult:
    """Evaluate a new order against the book. Open-position count includes the proposed order."""
    specs = dict(specs or {})
    specs.setdefault(order.symbol, spec)
    projected_positions = state.open_positions + (
        OpenPosition(
            ticket=order.ticket or "proposed",
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            entry_price=order.entry_price,
            current_price=order.entry_price,
            stop_loss=order.stop_loss,
            profit=Decimal("0"),
        ),
    )
    projected = AccountRiskState(
        equity=state.equity,
        balance=state.balance,
        margin=state.margin,
        free_margin=state.free_margin,
        margin_level=state.margin_level,
        day_start_equity=state.day_start_equity,
        peak_equity=state.peak_equity,
        trades_today=state.trades_today + 1,
        consecutive_losses=state.consecutive_losses,
        open_positions=projected_positions,
        last_entry_at=state.last_entry_at,
        control_state=state.control_state,
        currency=state.currency,
        exposure_account=state.exposure_account,
    )
    result = evaluate_account(projected, rules, specs, fx_rates, now, stale_input)
    # Re-run entry constraints against the pre-trade clock and the projected counts.
    entry_hits = _portfolio_hits(projected, rules, now or datetime.now().astimezone(), for_new_trade=True)
    # Drop duplicate portfolio hits already recorded by evaluate_account.
    existing = {(hit.code, hit.decision) for hit in result.hits}
    for hit in entry_hits:
        if (hit.code, hit.decision) not in existing:
            result.hits.append(hit)
    sized = position_risk(order, spec, state.equity, fx_to_account)
    result.risk_amount = sized.risk_amount
    result.risk_percent = sized.risk_percent
    if sized.unprotected:
        result.hits.append(
            _hit("MISSING_STOP", Decision.WARNING, order.symbol, "stop_loss", "Proposed order has no stop loss")
        )
    elif sized.incomplete:
        result.hits.append(
            _hit("INCOMPLETE_SPEC", Decision.WARNING, order.symbol, "symbol_spec", sized.reason or "incomplete spec")
        )
    elif sized.risk_percent is not None and _rule_on(rules, "RISK_PER_TRADE_PCT"):
        risk_decision = _utilization_decision(
            sized.risk_percent,
            rules.risk_per_trade_pct,
            rules.warning_utilization,
            Decision.BLOCK,
            inclusive=False,
        )
        if risk_decision:
            result.hits.append(
                _hit(
                    "MAX_RISK_PER_TRADE",
                    risk_decision,
                    f"{sized.risk_percent}",
                    f"{rules.risk_per_trade_pct}",
                    "Risk at the stop versus equity",
                )
            )
    if _rule_on(rules, "MAX_LOT") and order.volume > rules.max_lot:
        result.hits.append(
            _hit("MAX_LOT", Decision.BLOCK, f"{order.volume}", f"{rules.max_lot}", "Lot size above the account maximum")
        )
    elif _rule_on(rules, "MAX_LOT") and rules.max_lot > 0 and order.volume >= rules.max_lot * rules.warning_utilization:
        result.hits.append(
            _hit("MAX_LOT", Decision.WARNING, f"{order.volume}", f"{rules.max_lot}", "Lot size approaching the maximum")
        )
    result.decision = _strongest(result.hits)
    return result


def evaluate_fail_closed(
    state: AccountRiskState,
    rules: EffectiveRules,
    order: ProposedOrder | None = None,
    spec: SymbolSpec | None = None,
    fx_to_account: Decimal = Decimal("1"),
    specs: dict[str, SymbolSpec] | None = None,
    fx_rates: dict[str, Decimal] | None = None,
    now: datetime | None = None,
    stale_input: bool = False,
) -> RiskResult:
    """Run evaluation. Any unexpected failure blocks the new trade."""
    try:
        if order is None:
            return evaluate_account(state, rules, specs, fx_rates, now, stale_input)
        if spec is None:
            raise ValueError("symbol spec is required for a proposed order")
        return evaluate_proposed(
            state, rules, order, spec, fx_to_account, specs, fx_rates, now, stale_input
        )
    except Exception as exc:  # noqa: BLE001 — fail closed on the risk boundary
        return RiskResult(
            decision=Decision.BLOCK,
            hits=[
                _hit("ENGINE_FAILURE", Decision.BLOCK, exc.__class__.__name__, "success", "Risk engine failed closed")
            ],
            stale_input=stale_input,
        )

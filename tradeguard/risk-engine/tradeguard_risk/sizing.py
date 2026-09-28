from __future__ import annotations

from decimal import Decimal

from tradeguard_risk.money import D, floor_to_step, quantize_money
from tradeguard_risk.types import ProposedOrder, SizingError, SizingResult, SymbolSpec


def stop_distance(entry: Decimal, stop: Decimal) -> Decimal:
    return abs(D(entry) - D(stop))


def tick_count(entry: Decimal, stop: Decimal, tick_size: Decimal) -> Decimal:
    size = D(tick_size)
    if size <= 0:
        raise SizingError("tick_size must be positive")
    return stop_distance(entry, stop) / size


def loss_per_lot(
    entry: Decimal,
    stop: Decimal,
    spec: SymbolSpec,
    fx_to_account: Decimal,
) -> Decimal:
    """Account-currency loss for 1.0 lot if price reaches the stop."""
    fx = D(fx_to_account)
    if fx <= 0:
        raise SizingError("fx rate must be positive")
    if spec.tick_value < 0:
        raise SizingError("tick_value must be non-negative")
    ticks = tick_count(entry, stop, spec.tick_size)
    return quantize_money(ticks * D(spec.tick_value) * fx)


def position_risk(
    order: ProposedOrder,
    spec: SymbolSpec,
    equity: Decimal,
    fx_to_account: Decimal = Decimal("1"),
) -> SizingResult:
    equity_d = D(equity)
    if order.stop_loss is None:
        return SizingResult(
            risk_amount=None,
            risk_percent=None,
            loss_per_lot=None,
            suggested_volume=None,
            unprotected=True,
            incomplete=False,
            reason="missing_stop_loss",
        )
    if spec.tick_size <= 0 or spec.tick_value <= 0 or fx_to_account <= 0:
        return SizingResult(
            risk_amount=None,
            risk_percent=None,
            loss_per_lot=None,
            suggested_volume=None,
            unprotected=False,
            incomplete=True,
            reason="incomplete_symbol_spec",
        )
    try:
        per_lot = loss_per_lot(order.entry_price, order.stop_loss, spec, fx_to_account)
    except SizingError as exc:
        return SizingResult(
            risk_amount=None,
            risk_percent=None,
            loss_per_lot=None,
            suggested_volume=None,
            unprotected=False,
            incomplete=True,
            reason=str(exc),
        )
    amount = quantize_money(D(order.volume) * per_lot)
    percent = None
    if equity_d > 0:
        percent = quantize_money(amount / equity_d * Decimal("100"))
    suggested = None
    return SizingResult(
        risk_amount=amount,
        risk_percent=percent,
        loss_per_lot=per_lot,
        suggested_volume=suggested,
        unprotected=False,
        incomplete=False,
    )


def suggest_volume(
    equity: Decimal,
    risk_percent: Decimal,
    entry: Decimal,
    stop: Decimal | None,
    spec: SymbolSpec,
    fx_to_account: Decimal = Decimal("1"),
) -> SizingResult:
    if stop is None:
        return SizingResult(
            risk_amount=None,
            risk_percent=None,
            loss_per_lot=None,
            suggested_volume=None,
            unprotected=True,
            incomplete=False,
            reason="missing_stop_loss",
        )
    equity_d = D(equity)
    budget = quantize_money(equity_d * D(risk_percent) / Decimal("100"))
    try:
        per_lot = loss_per_lot(entry, stop, spec, fx_to_account)
    except SizingError as exc:
        return SizingResult(
            risk_amount=budget,
            risk_percent=D(risk_percent),
            loss_per_lot=None,
            suggested_volume=None,
            unprotected=False,
            incomplete=True,
            reason=str(exc),
        )
    if per_lot <= 0:
        return SizingResult(
            risk_amount=budget,
            risk_percent=D(risk_percent),
            loss_per_lot=per_lot,
            suggested_volume=None,
            unprotected=False,
            incomplete=True,
            reason="zero_loss_per_lot",
        )
    raw = budget / per_lot
    stepped = floor_to_step(raw, spec.volume_step)
    if stepped < spec.volume_min:
        return SizingResult(
            risk_amount=budget,
            risk_percent=D(risk_percent),
            loss_per_lot=per_lot,
            suggested_volume=None,
            unprotected=False,
            incomplete=False,
            reason="min_lot_exceeds_risk_budget",
        )
    if stepped > spec.volume_max:
        stepped = floor_to_step(spec.volume_max, spec.volume_step)
    return SizingResult(
        risk_amount=budget,
        risk_percent=D(risk_percent),
        loss_per_lot=per_lot,
        suggested_volume=stepped,
        unprotected=False,
        incomplete=False,
    )

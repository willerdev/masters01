from __future__ import annotations

from decimal import Decimal

from tradeguard_risk.money import D, quantize_money


def current_drawdown_pct(peak_equity: Decimal, equity: Decimal) -> Decimal:
    peak = D(peak_equity)
    current = D(equity)
    if peak <= 0 or current >= peak:
        return Decimal("0")
    return quantize_money((peak - current) / peak * Decimal("100"))


def daily_loss_pct(day_start_equity: Decimal, equity: Decimal) -> Decimal:
    start = D(day_start_equity)
    current = D(equity)
    if start <= 0 or current >= start:
        return Decimal("0")
    return quantize_money((start - current) / start * Decimal("100"))


def daily_pnl(day_start_equity: Decimal, equity: Decimal) -> Decimal:
    return quantize_money(D(equity) - D(day_start_equity))


def max_drawdown_pct(equity_points: list[Decimal]) -> Decimal:
    """Peak-to-trough drawdown across an equity series, in percent."""
    peak = Decimal("0")
    worst = Decimal("0")
    for point in equity_points:
        value = D(point)
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * Decimal("100")
            if dd > worst:
                worst = dd
    return quantize_money(worst)

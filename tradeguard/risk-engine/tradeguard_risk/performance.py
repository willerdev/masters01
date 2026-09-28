from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradeguard_risk.drawdown import max_drawdown_pct
from tradeguard_risk.money import D, quantize_money


@dataclass
class ClosedTradePnL:
    profit: Decimal


@dataclass
class PerformanceStats:
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: Decimal | None
    loss_rate: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    net_profit: Decimal
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    expectancy: Decimal | None
    average_risk_reward: Decimal | None
    max_drawdown_percent: Decimal
    recovery_factor: Decimal | None
    consecutive_wins: int
    consecutive_losses: int
    equity_sharpe_rf0_252: Decimal | None
    equity_return_mean: Decimal | None
    equity_return_stdev: Decimal | None


def _streaks(profits: list[Decimal]) -> tuple[int, int]:
    best_win = 0
    best_loss = 0
    win = 0
    loss = 0
    for profit in profits:
        if profit > 0:
            win += 1
            loss = 0
        elif profit < 0:
            loss += 1
            win = 0
        else:
            win = 0
            loss = 0
        best_win = max(best_win, win)
        best_loss = max(best_loss, loss)
    return best_win, best_loss


def _stdev(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    # Newton square root keeps the result in Decimal.
    guess = variance.sqrt() if hasattr(variance, "sqrt") else Decimal(variance) ** Decimal("0.5")
    return guess


def performance_stats(
    profits: list[Decimal],
    equity_points: list[Decimal] | None = None,
) -> PerformanceStats:
    values = [D(profit) for profit in profits]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    count = len(values)
    win_count = len(wins)
    loss_count = len(losses)
    gross_profit = quantize_money(sum(wins, Decimal("0")))
    gross_loss = quantize_money(sum((abs(value) for value in losses), Decimal("0")))
    net = quantize_money(sum(values, Decimal("0")))
    win_rate = quantize_money(Decimal(win_count) / Decimal(count)) if count else None
    loss_rate = quantize_money(Decimal(loss_count) / Decimal(count)) if count else None
    profit_factor = quantize_money(gross_profit / gross_loss) if gross_loss > 0 else None
    average_win = quantize_money(gross_profit / Decimal(win_count)) if win_count else None
    average_loss = quantize_money(gross_loss / Decimal(loss_count)) if loss_count else None
    expectancy = None
    if win_rate is not None and loss_rate is not None and average_win is not None and average_loss is not None:
        expectancy = quantize_money(win_rate * average_win - loss_rate * average_loss)
    rr = None
    if average_win is not None and average_loss not in (None, Decimal("0")):
        rr = quantize_money(average_win / average_loss)
    points = [D(point) for point in (equity_points or [])]
    max_dd = max_drawdown_pct(points) if points else Decimal("0")
    recovery = quantize_money(net / (points[0] * max_dd / Decimal("100"))) if points and max_dd > 0 and points[0] > 0 else None
    best_win, best_loss = _streaks(values)

    returns: list[Decimal] = []
    for previous, current in zip(points, points[1:]):
        if previous > 0:
            returns.append((current - previous) / previous)
    mean = None
    stdev = None
    sharpe = None
    if len(returns) >= 2:
        mean = quantize_money(sum(returns, Decimal("0")) / Decimal(len(returns)))
        stdev = quantize_money(_stdev(returns))
        if len(returns) >= 30 and stdev and stdev > 0 and mean is not None:
            sharpe = quantize_money(mean / stdev * Decimal("252").sqrt())
    return PerformanceStats(
        trade_count=count,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        loss_rate=loss_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net,
        profit_factor=profit_factor,
        average_win=average_win,
        average_loss=average_loss,
        expectancy=expectancy,
        average_risk_reward=rr,
        max_drawdown_percent=max_dd,
        recovery_factor=recovery,
        consecutive_wins=best_win,
        consecutive_losses=best_loss,
        equity_sharpe_rf0_252=sharpe,
        equity_return_mean=mean,
        equity_return_stdev=stdev,
    )

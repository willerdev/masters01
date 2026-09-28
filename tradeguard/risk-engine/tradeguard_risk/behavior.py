"""Observable trading-behavior measurements.

Bands describe how far a measurement sits from the configured threshold.
They are not a psychological diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from tradeguard_risk.money import D, quantize_money
from tradeguard_risk.overtrading import TradeSample, _hhi


@dataclass(frozen=True)
class BehaviorThresholds:
    trades_per_hour: Decimal = Decimal("6")
    min_interval_seconds: Decimal = Decimal("120")
    loss_reentry: int = 4
    lot_change: Decimal = Decimal("1.5")
    consecutive_losses: int = 5
    daily_trade_count: int = 12
    symbol_hhi: Decimal = Decimal("0.70")
    short_hold_seconds: Decimal = Decimal("60")
    drawdown_at_entry: Decimal = Decimal("5")
    trades_after_stop: int = 3


def _median_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return D(median(values))


def measure_behavior(trades: list[TradeSample], now: datetime, thresholds: BehaviorThresholds | None = None) -> dict:
    limits = thresholds or BehaviorThresholds()
    window = [trade for trade in trades if trade.open_time >= now - timedelta(hours=24)]
    window.sort(key=lambda trade: trade.open_time)
    gaps: list[Decimal] = []
    holds: list[Decimal] = []
    drawdowns: list[Decimal] = []
    loss_reentry = 0
    after_stop = 0
    previous_loss = False
    streak = 0
    worst_streak = 0
    volumes: list[Decimal] = []
    weights: dict[str, Decimal] = {}
    for index, trade in enumerate(window):
        volumes.append(D(trade.volume))
        weights[trade.symbol] = weights.get(trade.symbol, Decimal("0")) + D(trade.volume)
        end = trade.close_time or now
        holds.append(Decimal(str(max((end - trade.open_time).total_seconds(), 0))))
        if trade.drawdown_at_entry_pct is not None:
            drawdowns.append(D(trade.drawdown_at_entry_pct))
        if index:
            gaps.append(Decimal(str(max((trade.open_time - window[index - 1].open_time).total_seconds(), 0))))
        if previous_loss:
            loss_reentry += 1
        if trade.stop_loss_hit and index + 1 < len(window):
            after_stop += 1
        if trade.profit is not None and trade.profit < 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
            previous_loss = True
        else:
            streak = 0
            previous_loss = False
    count = len(window)
    per_hour = quantize_money(Decimal(count) / Decimal("24"))
    gap_median = _median_decimal(gaps)
    hold_median = _median_decimal(holds)
    dd_median = _median_decimal(drawdowns)
    lot_change = None
    if len(volumes) >= 2 and volumes[0] > 0:
        lot_change = quantize_money(volumes[-1] / _median_decimal(volumes[:-1] or volumes[:1]))
    symbol_hhi = _hhi(list(weights.values())) if weights else Decimal("0")
    features = {
        "trade_frequency": f"{per_hour:.4f}",
        "average_trade_interval": None if gap_median is None else f"{gap_median:.2f}",
        "loss_reentry_frequency": loss_reentry,
        "lot_size_change": None if lot_change is None else f"{lot_change:.4f}",
        "consecutive_losses": worst_streak,
        "daily_trade_count": count,
        "symbol_concentration": f"{symbol_hhi:.4f}",
        "holding_time": None if hold_median is None else f"{hold_median:.2f}",
        "drawdown_at_entry": None if dd_median is None else f"{dd_median:.2f}",
        "trades_after_stop_loss": after_stop,
        "sample_size": count,
    }
    observations = []
    if count:
        observations.append(f"{count} trades opened in the last 24 hours ({per_hour:.2f} per hour).")
    if gap_median is not None:
        observations.append(f"Median time between entries is {gap_median:.0f} seconds.")
    if lot_change is not None:
        observations.append(f"Latest lot is {lot_change:.2f} times the median of earlier lots in the window.")
    if worst_streak:
        observations.append(f"Longest measured loss streak in the window is {worst_streak}.")
    if after_stop:
        observations.append(f"{after_stop} entries followed a trade that closed at its stop.")
    breaches = []
    if per_hour >= limits.trades_per_hour:
        breaches.append("trade_frequency")
    if gap_median is not None and gap_median <= limits.min_interval_seconds:
        breaches.append("average_trade_interval")
    if loss_reentry >= limits.loss_reentry:
        breaches.append("loss_reentry_frequency")
    if lot_change is not None and lot_change >= limits.lot_change:
        breaches.append("lot_size_change")
    if worst_streak >= limits.consecutive_losses:
        breaches.append("consecutive_losses")
    if count >= limits.daily_trade_count:
        breaches.append("daily_trade_count")
    if symbol_hhi >= limits.symbol_hhi:
        breaches.append("symbol_concentration")
    if hold_median is not None and hold_median <= limits.short_hold_seconds:
        breaches.append("holding_time")
    if dd_median is not None and dd_median >= limits.drawdown_at_entry:
        breaches.append("drawdown_at_entry")
    if after_stop >= limits.trades_after_stop:
        breaches.append("trades_after_stop_loss")
    return {"features": features, "observations": observations, "threshold_breaches": breaches}

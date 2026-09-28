from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tradeguard_risk.money import D, quantize_money
from tradeguard_risk.types import OvertradingState


@dataclass(frozen=True)
class TradeSample:
    symbol: str
    volume: Decimal
    open_time: datetime
    close_time: datetime | None = None
    profit: Decimal | None = None
    notional: Decimal | None = None
    stop_loss_hit: bool = False
    drawdown_at_entry_pct: Decimal | None = None


@dataclass(frozen=True)
class OvertradingThresholds:
    trades_per_hour: tuple[Decimal, Decimal, Decimal] = (Decimal("3"), Decimal("6"), Decimal("10"))
    trades_per_day: tuple[Decimal, Decimal, Decimal] = (Decimal("8"), Decimal("12"), Decimal("20"))
    trades_after_losses: tuple[int, int, int] = (2, 4, 6)
    lot_escalation: tuple[Decimal, Decimal, Decimal] = (Decimal("1.25"), Decimal("1.5"), Decimal("2"))
    loss_streak: tuple[int, int, int] = (3, 5, 8)
    symbol_hhi: tuple[Decimal, Decimal, Decimal] = (Decimal("0.50"), Decimal("0.70"), Decimal("0.90"))
    exposure_hhi: tuple[Decimal, Decimal, Decimal] = (Decimal("0.50"), Decimal("0.70"), Decimal("0.90"))
    rapid_reentry: tuple[int, int, int] = (2, 4, 7)
    rapid_reentry_seconds: int = 60
    short_gap_seconds: tuple[int, int, int] = (300, 120, 45)
    short_hold_seconds: tuple[int, int, int] = (120, 60, 30)


@dataclass
class OvertradingMetrics:
    trades_per_hour: Decimal
    trades_per_day: int
    average_holding_seconds: Decimal | None
    average_seconds_between_trades: Decimal | None
    trades_after_losses: int
    lot_escalation: Decimal | None
    loss_streak: int
    symbol_concentration: Decimal
    exposure_concentration: Decimal
    rapid_reentry_count: int
    sample_size: int


@dataclass
class OvertradingAssessment:
    state: OvertradingState
    metrics: OvertradingMetrics
    bands: dict[str, int]


def _hhi(weights: list[Decimal]) -> Decimal:
    total = sum(weights, Decimal("0"))
    if total <= 0:
        return Decimal("0")
    score = sum((weight / total) ** 2 for weight in weights)
    return quantize_money(score)


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _band(value: Decimal, levels: tuple[Decimal, Decimal, Decimal], *, reverse: bool = False) -> int:
    low, mid, high = levels
    if reverse:
        if value <= high:
            return 3
        if value <= mid:
            return 2
        if value <= low:
            return 1
        return 0
    if value >= high:
        return 3
    if value >= mid:
        return 2
    if value >= low:
        return 1
    return 0


def _state_from_bands(bands: dict[str, int]) -> OvertradingState:
    if not bands:
        return OvertradingState.NORMAL
    worst = max(bands.values())
    average = sum(bands.values()) / len(bands)
    if worst >= 3 and average >= 1.5:
        return OvertradingState.CRITICAL
    if worst >= 3 or average >= 2:
        return OvertradingState.HIGH
    if worst >= 2 or average >= 1:
        return OvertradingState.ELEVATED
    return OvertradingState.NORMAL


def compute_metrics(trades: list[TradeSample], now: datetime, window_hours: int = 24) -> OvertradingMetrics:
    window_start = now - timedelta(hours=window_hours)
    in_window = [trade for trade in trades if trade.open_time >= window_start]
    in_window.sort(key=lambda trade: trade.open_time)
    count = len(in_window)
    hours = Decimal(window_hours) if window_hours else Decimal("1")
    per_hour = quantize_money(Decimal(count) / hours) if window_hours else Decimal(count)

    holds: list[Decimal] = []
    for trade in in_window:
        end = trade.close_time or now
        holds.append(Decimal(str(max((end - trade.open_time).total_seconds(), 0))))
    avg_hold = quantize_money(sum(holds, Decimal("0")) / Decimal(len(holds))) if holds else None

    gaps: list[Decimal] = []
    for previous, current in zip(in_window, in_window[1:]):
        gaps.append(Decimal(str((current.open_time - previous.open_time).total_seconds())))
    avg_gap = quantize_money(sum(gaps, Decimal("0")) / Decimal(len(gaps))) if gaps else None

    closed = [trade for trade in trades if trade.close_time is not None and trade.profit is not None]
    closed.sort(key=lambda trade: trade.close_time or trade.open_time)
    after_losses = 0
    rapid = 0
    streak = 0
    running = 0
    for index, trade in enumerate(closed):
        profit = D(trade.profit or 0)
        if profit < 0:
            running += 1
            streak = max(streak, running)
        else:
            running = 0
        if profit < 0 and index + 1 < len(closed):
            nxt = closed[index + 1]
            if nxt.open_time >= trade.close_time:  # type: ignore[operator]
                after_losses += 1
                delta = (nxt.open_time - trade.close_time).total_seconds()  # type: ignore[operator]
                if nxt.symbol == trade.symbol and delta <= 60:
                    rapid += 1

    # Rapid re-entry also counts open entries after a loss inside the window.
    rapid_window = 0
    ordered = sorted(trades, key=lambda trade: trade.open_time)
    for index, trade in enumerate(ordered):
        if trade.profit is None or trade.profit >= 0 or trade.close_time is None:
            continue
        for later in ordered[index + 1 :]:
            if later.open_time < trade.close_time:
                continue
            gap = (later.open_time - trade.close_time).total_seconds()
            if gap > 60:
                break
            if later.symbol == trade.symbol:
                rapid_window += 1
    rapid = max(rapid, rapid_window)

    volumes_before: list[Decimal] = []
    volumes_after: list[Decimal] = []
    loss_seen = False
    for trade in ordered:
        if loss_seen:
            volumes_after.append(D(trade.volume))
        else:
            volumes_before.append(D(trade.volume))
        if trade.profit is not None and trade.profit < 0:
            loss_seen = True
    baseline = _median(volumes_before) or _median([D(trade.volume) for trade in ordered])
    escalation = None
    if baseline and baseline > 0 and volumes_after:
        escalation = quantize_money((sum(volumes_after, Decimal("0")) / Decimal(len(volumes_after))) / baseline)

    symbol_weights: dict[str, Decimal] = {}
    exposure_weights: dict[str, Decimal] = {}
    for trade in in_window:
        symbol_weights[trade.symbol] = symbol_weights.get(trade.symbol, Decimal("0")) + D(trade.volume)
        notional = D(trade.notional) if trade.notional is not None else D(trade.volume)
        exposure_weights[trade.symbol] = exposure_weights.get(trade.symbol, Decimal("0")) + notional

    return OvertradingMetrics(
        trades_per_hour=per_hour,
        trades_per_day=count,
        average_holding_seconds=avg_hold,
        average_seconds_between_trades=avg_gap,
        trades_after_losses=after_losses,
        lot_escalation=escalation,
        loss_streak=streak,
        symbol_concentration=_hhi(list(symbol_weights.values())),
        exposure_concentration=_hhi(list(exposure_weights.values())),
        rapid_reentry_count=rapid,
        sample_size=count,
    )


def assess_overtrading(
    trades: list[TradeSample],
    now: datetime,
    thresholds: OvertradingThresholds | None = None,
    window_hours: int = 24,
) -> OvertradingAssessment:
    thresholds = thresholds or OvertradingThresholds()
    metrics = compute_metrics(trades, now, window_hours)
    bands: dict[str, int] = {}
    if metrics.sample_size == 0:
        return OvertradingAssessment(OvertradingState.NORMAL, metrics, bands)

    bands["trades_per_hour"] = _band(metrics.trades_per_hour, thresholds.trades_per_hour)
    bands["trades_per_day"] = _band(Decimal(metrics.trades_per_day), thresholds.trades_per_day)
    bands["trades_after_losses"] = _band(
        Decimal(metrics.trades_after_losses),
        tuple(Decimal(item) for item in thresholds.trades_after_losses),  # type: ignore[arg-type]
    )
    if metrics.lot_escalation is not None:
        bands["lot_escalation"] = _band(metrics.lot_escalation, thresholds.lot_escalation)
    bands["loss_streak"] = _band(
        Decimal(metrics.loss_streak),
        tuple(Decimal(item) for item in thresholds.loss_streak),  # type: ignore[arg-type]
    )
    if metrics.sample_size >= 2:
        bands["symbol_concentration"] = _band(metrics.symbol_concentration, thresholds.symbol_hhi)
        bands["exposure_concentration"] = _band(metrics.exposure_concentration, thresholds.exposure_hhi)
    bands["rapid_reentry"] = _band(
        Decimal(metrics.rapid_reentry_count),
        tuple(Decimal(item) for item in thresholds.rapid_reentry),  # type: ignore[arg-type]
    )
    if metrics.average_seconds_between_trades is not None and metrics.sample_size >= 3:
        bands["time_between_trades"] = _band(
            metrics.average_seconds_between_trades,
            tuple(Decimal(item) for item in thresholds.short_gap_seconds),  # type: ignore[arg-type]
            reverse=True,
        )
    if metrics.average_holding_seconds is not None and metrics.sample_size >= 3:
        bands["holding_time"] = _band(
            metrics.average_holding_seconds,
            tuple(Decimal(item) for item in thresholds.short_hold_seconds),  # type: ignore[arg-type]
            reverse=True,
        )
    return OvertradingAssessment(_state_from_bands(bands), metrics, bands)

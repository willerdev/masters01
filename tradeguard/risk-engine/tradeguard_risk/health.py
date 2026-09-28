from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradeguard_risk.money import D


RANK = {"HEALTHY": 0, "WARNING": 1, "HIGH_RISK": 2, "CRITICAL": 3}


@dataclass(frozen=True)
class HealthReason:
    code: str
    status: str
    measured: str
    threshold: str


@dataclass(frozen=True)
class HealthInput:
    risk_utilization_pct: Decimal
    drawdown_pct: Decimal
    max_drawdown_pct: Decimal
    margin_level: Decimal | None
    margin_warning: Decimal = Decimal("200")
    margin_danger: Decimal = Decimal("100")
    trades_today: int = 0
    max_trades_per_day: int = 10
    loss_streak: int = 0
    max_consecutive_losses: int = 5
    exposure_pct: Decimal = Decimal("0")
    max_exposure_pct: Decimal | None = None
    largest_symbol_share: Decimal = Decimal("0")
    connection_status: str = "pending"
    quote_stale: bool = False
    control_state: str = "ACTIVE"
    seconds_since_sync: int | None = None
    sync_stale_seconds: int = 90


def assess_health(data: HealthInput) -> tuple[str, list[HealthReason]]:
    reasons: list[HealthReason] = []
    drawdown_limit = D(data.max_drawdown_pct)
    utilization = D(data.risk_utilization_pct)
    drawdown = D(data.drawdown_pct)

    if data.control_state == "EMERGENCY_STOP":
        reasons.append(HealthReason("CONTROL_EMERGENCY_STOP", "CRITICAL", data.control_state, "ACTIVE"))
    if data.connection_status == "disconnected":
        reasons.append(HealthReason("CONNECTION_DOWN", "CRITICAL", data.connection_status, "connected"))
    if drawdown_limit > 0 and drawdown >= drawdown_limit:
        reasons.append(HealthReason("DRAWDOWN_LIMIT", "CRITICAL", f"{drawdown:.2f}%", f"{drawdown_limit:.2f}%"))
    if data.margin_level is not None and D(data.margin_level) > 0 and D(data.margin_level) <= D(data.margin_danger):
        reasons.append(HealthReason("MARGIN_DANGER", "CRITICAL", f"{D(data.margin_level):.2f}", f"{D(data.margin_danger):.2f}"))

    if drawdown_limit > 0 and drawdown >= drawdown_limit * Decimal("0.70"):
        reasons.append(HealthReason("DRAWDOWN_ELEVATED", "HIGH_RISK", f"{drawdown:.2f}%", f"{(drawdown_limit * Decimal('0.70')):.2f}%"))
    if data.max_consecutive_losses > 0 and data.loss_streak >= data.max_consecutive_losses:
        reasons.append(HealthReason("LOSS_STREAK", "HIGH_RISK", str(data.loss_streak), str(data.max_consecutive_losses)))
    if utilization >= Decimal("80"):
        reasons.append(HealthReason("RISK_UTILIZATION", "HIGH_RISK", f"{utilization:.2f}%", "80%"))
    if data.quote_stale:
        reasons.append(HealthReason("STALE_QUOTES", "HIGH_RISK", "stale", f"{data.sync_stale_seconds}s"))
    if data.seconds_since_sync is not None and data.seconds_since_sync > data.sync_stale_seconds:
        reasons.append(HealthReason("DATA_STALE", "HIGH_RISK", f"{data.seconds_since_sync}s", f"{data.sync_stale_seconds}s"))
    if data.max_exposure_pct is not None and D(data.max_exposure_pct) > 0 and D(data.exposure_pct) >= D(data.max_exposure_pct):
        reasons.append(HealthReason("EXPOSURE_LIMIT", "HIGH_RISK", f"{D(data.exposure_pct):.2f}%", f"{D(data.max_exposure_pct):.2f}%"))

    if data.connection_status not in {"connected", "disconnected"}:
        reasons.append(HealthReason("CONNECTION_PENDING", "WARNING", data.connection_status, "connected"))
    if data.control_state in {"PAUSED", "NEW_TRADES_DISABLED"}:
        reasons.append(HealthReason("TRADING_RESTRICTED", "WARNING", data.control_state, "ACTIVE"))
    if utilization >= Decimal("50"):
        reasons.append(HealthReason("RISK_UTILIZATION_WATCH", "WARNING", f"{utilization:.2f}%", "50%"))
    if data.max_trades_per_day > 0 and data.trades_today >= int(data.max_trades_per_day * 0.8):
        reasons.append(HealthReason("TRADE_FREQUENCY", "WARNING", str(data.trades_today), str(data.max_trades_per_day)))
    if D(data.largest_symbol_share) >= Decimal("0.70"):
        reasons.append(HealthReason("POSITION_CONCENTRATION", "WARNING", f"{D(data.largest_symbol_share):.2f}", "0.70"))
    if data.margin_level is not None and D(data.margin_level) > D(data.margin_danger) and D(data.margin_level) <= D(data.margin_warning):
        reasons.append(HealthReason("MARGIN_WATCH", "WARNING", f"{D(data.margin_level):.2f}", f"{D(data.margin_warning):.2f}"))

    if not reasons:
        return "HEALTHY", []
    status = max(reasons, key=lambda reason: RANK[reason.status]).status
    return status, reasons

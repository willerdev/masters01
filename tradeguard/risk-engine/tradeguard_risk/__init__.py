"""Deterministic TradeGuard risk engine.

This package has no I/O. Callers pass decimals and receive decisions.
"""

from tradeguard_risk.decisions import evaluate_account, evaluate_fail_closed, evaluate_proposed
from tradeguard_risk.drawdown import current_drawdown_pct, daily_loss_pct, max_drawdown_pct
from tradeguard_risk.overtrading import assess_overtrading, compute_metrics
from tradeguard_risk.performance import performance_stats
from tradeguard_risk.sizing import position_risk, suggest_volume
from tradeguard_risk.types import Decision, OvertradingState

__all__ = [
    "Decision",
    "OvertradingState",
    "assess_overtrading",
    "compute_metrics",
    "current_drawdown_pct",
    "daily_loss_pct",
    "evaluate_account",
    "evaluate_fail_closed",
    "evaluate_proposed",
    "max_drawdown_pct",
    "performance_stats",
    "position_risk",
    "suggest_volume",
]

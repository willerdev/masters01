from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Decision(str, Enum):
    ALLOW = "ALLOW"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class OvertradingState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ControlState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    NEW_TRADES_DISABLED = "NEW_TRADES_DISABLED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


DECISION_RANK = {
    Decision.ALLOW: 0,
    Decision.WARNING: 1,
    Decision.BLOCK: 2,
    Decision.EMERGENCY_STOP: 3,
}


class SizingError(Exception):
    """Raised when a size cannot be computed from the given spec."""


@dataclass(frozen=True)
class SymbolSpec:
    broker_symbol: str
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    profit_currency: str
    digits: int = 5
    asset_class: str = "forex"
    calc_mode: str = "forex"
    pip_size: Decimal | None = None


@dataclass(frozen=True)
class ProposedOrder:
    symbol: str
    side: str
    volume: Decimal
    entry_price: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    ticket: str | None = None


@dataclass(frozen=True)
class OpenPosition:
    ticket: str
    symbol: str
    side: str
    volume: Decimal
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal | None
    profit: Decimal
    open_time: datetime | None = None
    take_profit: Decimal | None = None


@dataclass(frozen=True)
class EffectiveRules:
    risk_per_trade_pct: Decimal = Decimal("1")
    max_daily_loss_pct: Decimal = Decimal("3")
    max_total_drawdown_pct: Decimal = Decimal("10")
    max_trades_per_day: int = 10
    max_open_positions: int = 5
    max_lot: Decimal = Decimal("0.20")
    max_consecutive_losses: int = 5
    min_minutes_between_trades: int = 5
    allow_trading: bool = True
    warning_utilization: Decimal = Decimal("0.80")
    margin_level_warning: Decimal = Decimal("200")
    margin_level_danger: Decimal = Decimal("100")
    max_exposure_pct: Decimal | None = None
    disabled: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AccountRiskState:
    equity: Decimal
    balance: Decimal
    margin: Decimal
    free_margin: Decimal
    margin_level: Decimal | None
    day_start_equity: Decimal
    peak_equity: Decimal
    trades_today: int
    consecutive_losses: int
    open_positions: tuple[OpenPosition, ...] = ()
    last_entry_at: datetime | None = None
    control_state: ControlState = ControlState.ACTIVE
    currency: str = "USD"
    exposure_account: Decimal = Decimal("0")


@dataclass(frozen=True)
class RuleHit:
    code: str
    decision: Decision
    observed: str
    limit: str
    message: str


@dataclass
class SizingResult:
    risk_amount: Decimal | None
    risk_percent: Decimal | None
    loss_per_lot: Decimal | None
    suggested_volume: Decimal | None
    unprotected: bool
    incomplete: bool
    reason: str | None = None


@dataclass
class RiskResult:
    decision: Decision
    hits: list[RuleHit] = field(default_factory=list)
    risk_amount: Decimal | None = None
    risk_percent: Decimal | None = None
    open_risk_amount: Decimal = Decimal("0")
    open_risk_percent: Decimal | None = None
    daily_loss_percent: Decimal = Decimal("0")
    drawdown_percent: Decimal = Decimal("0")
    stale_input: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW

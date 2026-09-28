from __future__ import annotations

from decimal import Decimal

from tradeguard_risk.types import EffectiveRules

from app.models.entities import RiskRule

DEFAULT_RULES: dict[str, Decimal | bool] = {
    "RISK_PER_TRADE_PCT": Decimal("1"),
    "MAX_DAILY_LOSS_PCT": Decimal("3"),
    "MAX_TOTAL_DRAWDOWN_PCT": Decimal("10"),
    "MAX_TRADES_PER_DAY": Decimal("10"),
    "MAX_OPEN_POSITIONS": Decimal("5"),
    "MAX_LOT": Decimal("0.20"),
    "MAX_CONSECUTIVE_LOSSES": Decimal("5"),
    "MIN_MINUTES_BETWEEN_TRADES": Decimal("5"),
    "ALLOW_TRADING": True,
    "MAX_EXPOSURE_PCT": Decimal("0"),
}

RULE_FIELDS = {
    "RISK_PER_TRADE_PCT": "risk_per_trade_pct",
    "MAX_DAILY_LOSS_PCT": "max_daily_loss_pct",
    "MAX_TOTAL_DRAWDOWN_PCT": "max_total_drawdown_pct",
    "MAX_TRADES_PER_DAY": "max_trades_per_day",
    "MAX_OPEN_POSITIONS": "max_open_positions",
    "MAX_LOT": "max_lot",
    "MAX_CONSECUTIVE_LOSSES": "max_consecutive_losses",
    "MIN_MINUTES_BETWEEN_TRADES": "min_minutes_between_trades",
    "ALLOW_TRADING": "allow_trading",
    "MAX_EXPOSURE_PCT": "max_exposure_pct",
}


def rules_from_rows(rows: list[RiskRule]) -> EffectiveRules:
    values: dict[str, Decimal | bool] = dict(DEFAULT_RULES)
    enabled_codes: set[str] = set()
    for row in rows:
        if row.code not in DEFAULT_RULES or not row.enabled:
            continue
        enabled_codes.add(row.code)
        if row.code == "ALLOW_TRADING" and row.bool_value is not None:
            values[row.code] = row.bool_value
        elif row.numeric_value is not None:
            values[row.code] = row.numeric_value
    disabled = {code for code in DEFAULT_RULES if code not in enabled_codes}
    exposure = values["MAX_EXPOSURE_PCT"]
    return EffectiveRules(
        risk_per_trade_pct=Decimal(values["RISK_PER_TRADE_PCT"]),
        max_daily_loss_pct=Decimal(values["MAX_DAILY_LOSS_PCT"]),
        max_total_drawdown_pct=Decimal(values["MAX_TOTAL_DRAWDOWN_PCT"]),
        max_trades_per_day=int(values["MAX_TRADES_PER_DAY"]),
        max_open_positions=int(values["MAX_OPEN_POSITIONS"]),
        max_lot=Decimal(values["MAX_LOT"]),
        max_consecutive_losses=int(values["MAX_CONSECUTIVE_LOSSES"]),
        min_minutes_between_trades=int(values["MIN_MINUTES_BETWEEN_TRADES"]),
        allow_trading=bool(values["ALLOW_TRADING"]),
        max_exposure_pct=None if Decimal(exposure) <= 0 else Decimal(exposure),
        disabled=frozenset(disabled),
    )


def apply_rule_update(row: RiskRule, raw: object) -> None:
    if row.code == "ALLOW_TRADING":
        row.bool_value = bool(raw)
        row.numeric_value = None
        return
    row.numeric_value = Decimal(str(raw))
    row.bool_value = None

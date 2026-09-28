from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ruleset import rules_from_rows
from app.models.entities import Account, AccountState, ClosedTrade, DailyStatistic, MarketQuote, Position, RiskProfile, RiskRule
from tradeguard_risk.drawdown import current_drawdown_pct
from tradeguard_risk.health import HealthInput, assess_health
from tradeguard_risk.quotes import quote_is_stale
from app.core.config import get_settings


def _rules(db: Session, account: Account):
    profile = db.scalar(select(RiskProfile).where(RiskProfile.account_id == account.id))
    rows = [] if profile is None else db.scalars(select(RiskRule).where(RiskRule.profile_id == profile.id)).all()
    return rules_from_rows(rows)


def _loss_streak(db: Session, account_id) -> int:
    rows = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account_id).order_by(ClosedTrade.close_time.desc()).limit(30)).all()
    streak = 0
    for row in rows:
        if row.profit < 0:
            streak += 1
        else:
            break
    return streak


def account_health(db: Session, account: Account) -> dict:
    state = db.get(AccountState, account.id)
    rules = _rules(db, account)
    positions = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    equity = state.equity if state else Decimal("0")
    open_risk = db.scalar(select(func.coalesce(func.sum(Position.risk_amount), 0)).where(Position.account_id == account.id, Position.status == "open")) or Decimal("0")
    utilization = Decimal("0") if equity <= 0 else open_risk / equity * Decimal("100")
    notionals: dict[str, Decimal] = {}
    for position in positions:
        notionals[position.symbol] = notionals.get(position.symbol, Decimal("0")) + abs(position.volume * position.current_price)
    exposure = sum(notionals.values(), Decimal("0"))
    exposure_pct = Decimal("0") if equity <= 0 else exposure / equity * Decimal("100")
    largest = Decimal("0")
    if exposure > 0:
        largest = max(notionals.values()) / exposure
    quote_time = db.scalar(select(func.max(MarketQuote.captured_at)).where(MarketQuote.account_id == account.id))
    now = datetime.now(timezone.utc)
    stale = bool(positions) and quote_is_stale(quote_time, now, get_settings().stale_quote_seconds)
    sync_age = None
    if account.last_sync_at is not None:
        sync_age = int((now - account.last_sync_at).total_seconds())
    trades_today = 0
    if state and state.trading_date is not None:
        trades_today = int(
            db.scalar(
                select(func.coalesce(func.sum(DailyStatistic.trade_count), 0)).where(
                    DailyStatistic.account_id == account.id,
                    DailyStatistic.trading_date == state.trading_date,
                )
            )
            or 0
        )
    status, reasons = assess_health(
        HealthInput(
            risk_utilization_pct=utilization,
            drawdown_pct=current_drawdown_pct(state.peak_equity if state else 0, equity),
            max_drawdown_pct=Decimal("0") if "MAX_TOTAL_DRAWDOWN_PCT" in rules.disabled else rules.max_total_drawdown_pct,
            margin_level=None if state is None else state.margin_level,
            trades_today=trades_today,
            max_trades_per_day=0 if "MAX_TRADES_PER_DAY" in rules.disabled else rules.max_trades_per_day,
            loss_streak=_loss_streak(db, account.id),
            max_consecutive_losses=0 if "MAX_CONSECUTIVE_LOSSES" in rules.disabled else rules.max_consecutive_losses,
            exposure_pct=exposure_pct,
            max_exposure_pct=None if "MAX_EXPOSURE_PCT" in rules.disabled else rules.max_exposure_pct,
            largest_symbol_share=largest,
            connection_status=account.status,
            quote_stale=stale,
            control_state=account.control_state,
            seconds_since_sync=sync_age,
            sync_stale_seconds=get_settings().heartbeat_timeout_seconds,
        )
    )
    return {
        "status": status,
        "reasons": [{"code": reason.code, "status": reason.status, "measured": reason.measured, "threshold": reason.threshold} for reason in reasons],
    }

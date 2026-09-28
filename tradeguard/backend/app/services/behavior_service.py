from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account, ClosedTrade, Position
from tradeguard_risk.behavior import measure_behavior
from tradeguard_risk.overtrading import TradeSample, assess_overtrading


def account_behavior(db: Session, account: Account) -> dict:
    now = datetime.now(timezone.utc)
    samples = []
    for trade in db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account.id)).all():
        opened = trade.open_time or trade.close_time or now
        stop_hit = trade.stop_loss is not None and trade.close_price == trade.stop_loss
        samples.append(TradeSample(trade.symbol, trade.volume, opened, trade.close_time, trade.profit, stop_loss_hit=stop_hit))
    for position in db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all():
        samples.append(TradeSample(position.symbol, position.volume, position.open_time or now, None, position.profit))
    measured = measure_behavior(samples, now)
    state = assess_overtrading(samples, now)
    measured["overtrading_state"] = state.state.value
    measured["note"] = "Figures describe observed order flow. They are not a psychological assessment."
    return measured

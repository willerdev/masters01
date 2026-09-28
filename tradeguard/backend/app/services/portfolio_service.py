from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import AccountState, Position, User
from app.services.account_service import visible_account_query
from tradeguard_risk.portfolio import PortfolioAccount, PortfolioPosition, portfolio_snapshot


def portfolio_for(db: Session, user: User, roles: list[str]) -> dict:
    accounts = []
    for account in db.scalars(visible_account_query(db, user, roles)).all():
        state = db.get(AccountState, account.id)
        positions = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
        open_risk = db.scalar(select(func.coalesce(func.sum(Position.risk_amount), 0)).where(Position.account_id == account.id, Position.status == "open")) or Decimal("0")
        accounts.append(
            PortfolioAccount(
                account_id=str(account.id),
                name=account.display_name,
                balance=state.balance if state else Decimal("0"),
                equity=state.equity if state else Decimal("0"),
                peak_equity=state.peak_equity if state else Decimal("0"),
                open_risk=open_risk,
                positions=[PortfolioPosition(row.symbol, abs(row.volume * row.current_price), row.side) for row in positions],
            )
        )
    return portfolio_snapshot(accounts)

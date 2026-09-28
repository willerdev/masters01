from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tradeguard_risk.drawdown import max_drawdown_pct
from tradeguard_risk.performance import performance_stats

from app.models.entities import (
    Account,
    AccountState,
    ClosedTrade,
    DailyStatistic,
    DrawdownSnapshot,
    EquitySnapshot,
    MarketQuote,
    Position,
    RiskDecisionRow,
    RiskViolation,
    User,
)
from app.services.account_service import visible_account_query
from tradeguard_risk.quotes import quote_is_stale
from app.core.config import get_settings


def _money(value: Decimal | None) -> str:
    return f"{(value or Decimal('0')):.2f}"


def summary(db: Session, user: User, roles: list[str]) -> dict:
    accounts = db.scalars(visible_account_query(db, user, roles)).all()
    ids = [account.id for account in accounts]
    balance = Decimal("0")
    equity = Decimal("0")
    open_risk = Decimal("0")
    today_pl = Decimal("0")
    today_loss = Decimal("0")
    current_dd = Decimal("0")
    max_dd = Decimal("0")
    open_positions = 0
    trades_today = 0
    connected = 0
    worst = "HEALTHY" if accounts else "UNKNOWN"
    rank = {"HEALTHY": 0, "WARNING": 1, "HIGH_RISK": 2, "CRITICAL": 3, "UNKNOWN": -1}
    for account in accounts:
        state = db.get(AccountState, account.id)
        if account.status == "connected":
            connected += 1
        if state:
            balance += state.balance or 0
            equity += state.equity or 0
            if state.day_start_equity:
                delta = (state.equity or 0) - state.day_start_equity
                today_pl += delta
                if delta < 0:
                    today_loss += abs(delta)
            if state.peak_equity and state.equity is not None and state.peak_equity > 0 and state.equity < state.peak_equity:
                dd = (state.peak_equity - state.equity) / state.peak_equity * Decimal("100")
                current_dd = max(current_dd, dd)
        points = list(db.scalars(select(EquitySnapshot.equity).where(EquitySnapshot.account_id == account.id)).all())
        if points:
            max_dd = max(max_dd, max_drawdown_pct(points))
        open_positions += db.scalar(select(func.count()).select_from(Position).where(Position.account_id == account.id, Position.status == "open")) or 0
        open_risk += db.scalar(select(func.coalesce(func.sum(Position.risk_amount), 0)).where(Position.account_id == account.id, Position.status == "open")) or 0
        if state and state.trading_date is not None:
            trades_today += db.scalar(
                select(func.coalesce(func.sum(DailyStatistic.trade_count), 0)).where(
                    DailyStatistic.account_id == account.id,
                    DailyStatistic.trading_date == state.trading_date,
                )
            ) or 0
        health = _health(db, account, state)
        if rank[health] > rank[worst]:
            worst = health
    violations = 0
    if ids:
        violations = db.scalar(
            select(func.count()).select_from(RiskViolation).where(RiskViolation.account_id.in_(ids), RiskViolation.status == "open")
        ) or 0
    return {
        "total_accounts": len(accounts),
        "connected_accounts": connected,
        "total_balance": _money(balance),
        "total_equity": _money(equity),
        "total_open_risk": _money(open_risk),
        "today_pl": _money(today_pl),
        "today_loss": _money(today_loss),
        "current_drawdown": f"{current_dd:.2f}",
        "max_drawdown": f"{max_dd:.2f}",
        "open_positions": int(open_positions),
        "trades_today": int(trades_today),
        "risk_violations": int(violations),
        "account_health": worst,
    }


def _health(db: Session, account: Account, state: AccountState | None) -> str:
    from app.services.health_service import account_health

    return account_health(db, account)["status"]


def charts(db: Session, user: User, roles: list[str], account_id=None) -> dict:
    query = visible_account_query(db, user, roles)
    if account_id is not None:
        query = query.where(Account.id == account_id)
    accounts = db.scalars(query).all()
    ids = [account.id for account in accounts]
    equity_buckets: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    drawdown_buckets: dict[str, Decimal] = {}
    now_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    live_equity = Decimal("0")
    live_today = Decimal("0")
    today_key = datetime.now(timezone.utc).date().isoformat()
    has_live_today = False
    for account in accounts:
        state = db.get(AccountState, account.id)
        if state is None or state.equity is None:
            continue
        live_equity += state.equity
        if state.day_start_equity is not None:
            live_today += state.equity - state.day_start_equity
            has_live_today = True
            if state.trading_date is not None:
                today_key = state.trading_date.isoformat()
    if ids:
        for row in db.scalars(select(EquitySnapshot).where(EquitySnapshot.account_id.in_(ids)).order_by(EquitySnapshot.captured_at)).all():
            key = row.captured_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
            equity_buckets[key] += row.equity
        if live_equity:
            equity_buckets[now_key] = live_equity
        running_peak = Decimal("0")
        for key, value in equity_buckets.items():
            running_peak = max(running_peak, value)
            drawdown_buckets[key] = Decimal("0") if running_peak <= 0 else (running_peak - value) / running_peak * Decimal("100")
    daily = []
    frequency: dict[str, int] = defaultdict(int)
    wins = 0
    losses = 0
    exposure: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    utilization = []
    if ids:
        stats = db.scalars(select(DailyStatistic).where(DailyStatistic.account_id.in_(ids)).order_by(DailyStatistic.trading_date)).all()
        by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for stat in stats:
            by_date[stat.trading_date.isoformat()] += (stat.end_equity - stat.start_equity)
        if has_live_today:
            by_date[today_key] = live_today
        daily = [{"date": key, "pnl": f"{value:.2f}"} for key, value in by_date.items()]
        for trade in db.scalars(select(ClosedTrade).where(ClosedTrade.account_id.in_(ids))).all():
            if trade.profit > 0:
                wins += 1
            elif trade.profit < 0:
                losses += 1
            if trade.open_time:
                frequency[trade.open_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:00")] += 1
        for position in db.scalars(select(Position).where(Position.account_id.in_(ids), Position.status == "open")).all():
            exposure[position.symbol] += abs(position.volume * position.current_price)
    for account in accounts:
        state = db.get(AccountState, account.id)
        risk = db.scalar(select(func.coalesce(func.sum(Position.risk_amount), 0)).where(Position.account_id == account.id, Position.status == "open"))
        equity = state.equity if state and state.equity else Decimal("0")
        percent = Decimal("0") if equity <= 0 else (risk or Decimal("0")) / equity * Decimal("100")
        utilization.append({"account": account.display_name, "percent": f"{percent:.2f}"})
    profits = []
    if ids:
        profits = [row.profit for row in db.scalars(select(ClosedTrade).where(ClosedTrade.account_id.in_(ids))).all()]
    equity_points = list(equity_buckets.values())
    stats = performance_stats(profits, equity_points)
    return {
        "equity": [{"t": key, "equity": f"{value:.2f}"} for key, value in equity_buckets.items()],
        "drawdown": [{"t": key, "drawdown": f"{value:.2f}"} for key, value in drawdown_buckets.items()],
        "daily_pnl": daily,
        "trade_frequency": [{"bucket": key, "count": value} for key, value in sorted(frequency.items())],
        "risk_utilization": utilization,
        "exposure": [{"symbol": key, "notional": f"{value:.2f}"} for key, value in exposure.items()],
        "win_loss": {"wins": wins, "losses": losses},
        "performance": {
            "win_rate": None if stats.win_rate is None else f"{stats.win_rate:.4f}",
            "profit_factor": None if stats.profit_factor is None else f"{stats.profit_factor:.4f}",
            "expectancy": None if stats.expectancy is None else f"{stats.expectancy:.4f}",
            "average_win": None if stats.average_win is None else f"{stats.average_win:.2f}",
            "average_loss": None if stats.average_loss is None else f"{stats.average_loss:.2f}",
            "consecutive_wins": stats.consecutive_wins,
            "consecutive_losses": stats.consecutive_losses,
            "equity_sharpe_rf0_252": None if stats.equity_sharpe_rf0_252 is None else f"{stats.equity_sharpe_rf0_252:.4f}",
        },
    }


def latest_quotes(db: Session, account: Account) -> list[dict]:
    rows = db.scalars(select(MarketQuote).where(MarketQuote.account_id == account.id).order_by(MarketQuote.captured_at.desc()).limit(50)).all()
    seen = set()
    items = []
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.symbol in seen:
            continue
        seen.add(row.symbol)
        stale = quote_is_stale(row.captured_at, now, get_settings().stale_quote_seconds)
        items.append(
            {
                "symbol": row.symbol,
                "bid": str(row.bid),
                "ask": str(row.ask),
                "spread": str(row.spread),
                "tick": None if row.tick_size is None else str(row.tick_size),
                "timestamp": row.captured_at.isoformat(),
                "source": row.source,
                "stale": stale,
            }
        )
    return items

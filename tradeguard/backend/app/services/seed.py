from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.entities import (
    Account,
    AccountConnection,
    AccountGrant,
    AccountState,
    ClosedTrade,
    DailyStatistic,
    DrawdownSnapshot,
    EquitySnapshot,
    Organization,
    Position,
    RiskViolation,
    Role,
    User,
    UserRole,
)
from app.services.account_service import ensure_account_profile, ensure_default_profile
from tradeguard_risk.drawdown import current_drawdown_pct


def seed_admin(db: Session) -> None:
    settings = get_settings()
    if not settings.seed_admin_email or not settings.seed_admin_password:
        return
    if settings.environment == "production" and settings.seed_admin_password in {"changeme", "change-me"}:
        raise RuntimeError("Refusing the default admin password in production")
    existing = db.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    if existing:
        return
    org = Organization(name="TradeGuard", slug="tradeguard-local")
    db.add(org)
    db.flush()
    user = User(
        organization_id=org.id,
        email=settings.seed_admin_email.lower(),
        password_hash=hash_password(settings.seed_admin_password),
        full_name=settings.seed_admin_name,
    )
    db.add(user)
    db.flush()
    role = db.scalar(select(Role).where(Role.code == "SUPER_ADMIN"))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    ensure_default_profile(db, org.id)


def seed_sample(db: Session) -> None:
    user = db.scalar(select(User).where(User.email == get_settings().seed_admin_email.lower()))
    if user is None:
        return
    if db.scalar(select(Account).where(Account.account_number == "SAMPLE-1001")):
        return
    account = Account(
        organization_id=user.organization_id,
        display_name="Sample book",
        broker="Sample Broker",
        server="Sample-Live",
        account_number="SAMPLE-1001",
        connection_method="webhook",
        currency="USD",
        leverage=Decimal("100"),
        status="connected",
        monitoring_enabled=True,
        trading_day_timezone="UTC",
        last_sync_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.flush()
    db.add(AccountGrant(account_id=account.id, user_id=user.id))
    ensure_account_profile(db, account)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    equity = Decimal("10000")
    peak = equity
    points = []
    for day in range(30):
        if day < 18:
            equity += Decimal("40")
        elif day < 24:
            equity -= Decimal("180")
        else:
            equity += Decimal("25")
        peak = max(peak, equity)
        captured = now - timedelta(days=29 - day)
        points.append((captured, equity, peak))
    latest_equity = points[-1][1]
    latest_peak = points[-1][2]
    db.add(
        AccountState(
            account_id=account.id,
            balance=latest_equity - Decimal("35"),
            equity=latest_equity,
            margin=Decimal("420"),
            free_margin=latest_equity - Decimal("420"),
            margin_level=latest_equity / Decimal("420") * Decimal("100"),
            peak_equity=latest_peak,
            day_start_equity=latest_equity + Decimal("48"),
            trading_date=now.date(),
            as_of=now,
            stale=False,
        )
    )
    db.add(AccountConnection(account_id=account.id, method="webhook", status="connected", last_heartbeat_at=now, last_success_at=now))
    for captured, value, peak_value in points:
        db.add(EquitySnapshot(account_id=account.id, captured_at=captured, equity=value, balance=value))
        dd = current_drawdown_pct(peak_value, value)
        db.add(
            DrawdownSnapshot(
                account_id=account.id,
                captured_at=captured,
                equity=value,
                peak_equity=peak_value,
                drawdown_abs=max(peak_value - value, Decimal("0")),
                drawdown_pct=dd,
            )
        )
        db.add(
            DailyStatistic(
                account_id=account.id,
                trading_date=captured.date(),
                start_equity=value - Decimal("20"),
                end_equity=value,
                realized_pnl=Decimal("20") if value >= peak_value else Decimal("-40"),
                trade_count=2,
                win_count=1,
                loss_count=1,
            )
        )
    opened = now - timedelta(hours=5)
    db.add(
        Position(
            account_id=account.id,
            ticket="880001",
            symbol="EURUSD",
            side="buy",
            volume=Decimal("0.10"),
            entry_price=Decimal("1.08500"),
            current_price=Decimal("1.08620"),
            stop_loss=Decimal("1.08200"),
            take_profit=Decimal("1.09000"),
            profit=Decimal("12"),
            risk_amount=Decimal("30"),
            risk_percent=Decimal("0.29"),
            open_time=opened,
            magic_number=51001,
            comment="london-break",
            strategy="london-break",
            status="open",
        )
    )
    db.add(
        Position(
            account_id=account.id,
            ticket="880002",
            symbol="XAUUSD",
            side="sell",
            volume=Decimal("0.05"),
            entry_price=Decimal("2330.10"),
            current_price=Decimal("2324.40"),
            stop_loss=Decimal("2338.00"),
            take_profit=Decimal("2310.00"),
            profit=Decimal("28.50"),
            risk_amount=Decimal("39.50"),
            risk_percent=Decimal("0.38"),
            open_time=now - timedelta(hours=2),
            magic_number=51002,
            comment="metal-mean",
            strategy="metal-mean",
            status="open",
        )
    )
    db.add(
        ClosedTrade(
            account_id=account.id,
            ticket="770001",
            symbol="EURUSD",
            side="buy",
            volume=Decimal("0.10"),
            entry_price=Decimal("1.08000"),
            close_price=Decimal("1.08320"),
            profit=Decimal("32"),
            open_time=now - timedelta(days=1, hours=3),
            close_time=now - timedelta(days=1, hours=1),
            magic_number=51001,
            comment="london-break",
            strategy="london-break",
        )
    )
    db.add(
        ClosedTrade(
            account_id=account.id,
            ticket="770002",
            symbol="USDJPY",
            side="sell",
            volume=Decimal("0.20"),
            entry_price=Decimal("149.200"),
            close_price=Decimal("149.450"),
            profit=Decimal("-40"),
            open_time=now - timedelta(days=2, hours=4),
            close_time=now - timedelta(days=2, hours=3),
            magic_number=51003,
            comment="asia-fade",
            strategy="asia-fade",
        )
    )
    db.add(
        RiskViolation(
            account_id=account.id,
            code="MAX_LOT",
            severity="WARNING",
            observed_value="0.18",
            limit_value="0.20",
            message="Lot size approaching the maximum",
            status="open",
        )
    )

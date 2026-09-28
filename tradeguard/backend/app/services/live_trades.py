from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.connectors.registry import connector_for
from app.models.entities import Account, AccountConnection, DrawdownSnapshot, EquitySnapshot, Position, User
from tradeguard_risk.drawdown import current_drawdown_pct
from app.services.account_service import load_credentials, visible_account_query
from app.services.ingest_service import _state, _trading_date, _upsert_position


_sync_errors: dict[str, str] = {}


def terminal_accounts(db: Session) -> list[Account]:
    accounts = db.scalars(select(Account).where(Account.connection_method.in_(["metaapi", "local_mt5"]))).all()
    live: list[Account] = []
    for account in accounts:
        link = db.scalar(select(AccountConnection).where(AccountConnection.account_id == account.id))
        if link is not None and link.last_success_at is not None:
            live.append(account)
    return live


_history_at: dict[str, float] = {}


def refresh_live_books(db: Session) -> None:
    accounts = terminal_accounts(db)
    refresh_open_trades(db, accounts)
    _sync_histories(db, accounts)
    from app.services.naked_limits import remind_naked_limits
    from app.services.setup_watch import watch_setups
    from app.services.trade_watch import watch_open_trades

    watch_open_trades(db, accounts)
    watch_setups(db, accounts)
    remind_naked_limits(db)


def _sync_histories(db: Session, accounts: list[Account]) -> None:
    import time

    from app.services.journal_service import _sync_terminal_history

    now = time.monotonic()
    for account in accounts:
        key = str(account.id)
        if now - _history_at.get(key, 0) < 900:
            continue
        _history_at[key] = now
        _sync_terminal_history(db, account)


def current_sync_errors(accounts: list[Account]) -> list[dict]:
    errors: list[dict] = []
    for account in accounts:
        detail = _sync_errors.get(str(account.id))
        if detail:
            errors.append({"account_id": str(account.id), "account": account.display_name, "detail": detail})
    return errors


def connected_accounts(db: Session, user: User, roles: list[str]) -> list[Account]:
    accounts = db.scalars(visible_account_query(db, user, roles)).all()
    connected: list[Account] = []
    for account in accounts:
        link = db.scalar(select(AccountConnection).where(AccountConnection.account_id == account.id))
        if account.connection_method in {"metaapi", "local_mt5"} and link is not None and link.last_success_at is not None:
            connected.append(account)
            continue
        if account.status == "connected" or (link is not None and link.status == "connected"):
            connected.append(account)
    return connected


def refresh_open_trades(db: Session, accounts: list[Account]) -> list[dict]:
    """Pull the open book from each terminal that can answer. A failed pull leaves the stored book unchanged."""
    errors: list[dict] = []
    for account in accounts:
        if account.connection_method == "webhook":
            continue
        error = refresh_terminal(db, account)
        if error:
            errors.append(error)
    return errors


def refresh_terminal(db: Session, account: Account) -> dict | None:
    """Read open trades and account equity from one terminal. A failed read leaves the stored book unchanged."""
    if account.connection_method == "webhook":
        return None
    key = str(account.id)
    connector = connector_for(account.connection_method)
    fetch = getattr(connector, "fetch_positions", None)
    if fetch is None:
        detail = "This connection cannot read open trades"
        _sync_errors[key] = detail
        return {"account_id": key, "account": account.display_name, "detail": detail}
    try:
        credentials = load_credentials(db, account.id)
        positions = fetch(credentials)
    except Exception as exc:  # noqa: BLE001
        detail = _safe_detail(exc)
        _sync_errors[key] = detail
        return {"account_id": key, "account": account.display_name, "detail": detail}
    _sync_errors.pop(key, None)
    _replace_open_book(db, account, positions)
    fetch_account = getattr(connector, "fetch_account", None)
    if fetch_account is not None:
        try:
            info = fetch_account(credentials)
        except Exception:  # noqa: BLE001
            info = None
        if info is not None:
            _apply_live_state(db, account, info)
    _mark_terminal_alive(db, account)
    account.last_sync_at = datetime.now(timezone.utc)
    return None


def _apply_live_state(db: Session, account: Account, info) -> None:
    state = _state(db, account)
    now = datetime.now(timezone.utc)
    today = _trading_date(account, now)
    if state.trading_date != today:
        state.day_start_equity = info.equity
        state.trading_date = today
    if state.peak_equity is None or info.equity > state.peak_equity:
        state.peak_equity = info.equity
    state.balance = info.balance
    state.equity = info.equity
    state.margin = info.margin
    state.free_margin = info.free_margin
    state.margin_level = info.margin_level
    state.as_of = now
    state.stale = False
    _record_equity_point(db, account, state, now)


def _record_equity_point(db: Session, account: Account, state, now: datetime) -> None:
    latest = db.scalar(
        select(EquitySnapshot.captured_at).where(EquitySnapshot.account_id == account.id).order_by(EquitySnapshot.captured_at.desc()).limit(1)
    )
    if latest is not None and (now - latest).total_seconds() < 60:
        return
    equity = state.equity or 0
    balance = state.balance or 0
    db.add(EquitySnapshot(account_id=account.id, captured_at=now, equity=equity, balance=balance))
    peak = state.peak_equity or equity
    db.add(
        DrawdownSnapshot(
            account_id=account.id,
            captured_at=now,
            equity=equity,
            peak_equity=peak,
            drawdown_abs=max(peak - equity, 0),
            drawdown_pct=current_drawdown_pct(peak, equity),
        )
    )


def _mark_terminal_alive(db: Session, account: Account) -> None:
    now = datetime.now(timezone.utc)
    account.status = "connected"
    link = db.scalar(select(AccountConnection).where(AccountConnection.account_id == account.id))
    if link is None:
        return
    link.status = "connected"
    link.last_heartbeat_at = now
    link.last_success_at = now
    link.last_error_code = ""


def _replace_open_book(db: Session, account: Account, positions: list) -> None:
    live = {str(position.ticket) for position in positions}
    stored = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    for row in stored:
        if row.ticket not in live:
            row.status = "closed"
    for position in positions:
        _upsert_position(db, account, position)
    db.flush()


def _safe_detail(exc: Exception) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if not text or any(word in lowered for word in ("token", "password", "auth-token", "api_key")):
        return "The terminal did not return open trades"
    return text[:180]

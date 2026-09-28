"""A private Telegram setup is watched. A missing stop is set at 100 pips and a missing target at 2R before the limit is sent."""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account, SetupWatch, User

logger = logging.getLogger(__name__)


def consider_setup(db: Session, organization_id: UUID, chat_id: str, text: str, *, from_image: bool = False) -> str | None:
    from app.services.ai_service import extract_signal

    found = extract_signal(db, organization_id, text)
    if not found:
        return None
    if found.get("entry") is None:
        return None
    missing = found.get("stop_loss") is None or found.get("take_profit") is None or found.get("volume") is None
    if missing:
        if not from_image and not _looks_like_setup(text):
            return None
        found = _fill_missing(db, organization_id, found)
        if found.get("stop_loss") is None or found.get("take_profit") is None:
            return f"I read {found['side']} {found['symbol']} at {_plain(found['entry'])}, but I could not calculate a stop for it."
    return _arm(db, organization_id, chat_id, found)


def _fill_missing(db: Session, organization_id: UUID, found: dict) -> dict:
    """A missing stop is 100 pips, a missing target is 2R, and a missing lot is the Deriv minimum."""
    from app.connectors.synthetic_lots import minimum_lot, pip_size, plan_protection

    account = _quote_account(db, organization_id)
    spec = None
    if account is not None:
        from app.services.ingest_service import _spec_for

        spec = _spec_for(db, account, found["symbol"])
    pip = pip_size(found["symbol"], spec)
    stop, take, auto_stop, auto_target = plan_protection(found["side"], found["entry"], found.get("stop_loss"), found.get("take_profit"), pip, 100)
    volume = found.get("volume") or minimum_lot(found["symbol"]) or Decimal("0.01")
    return {**found, "stop_loss": stop, "take_profit": take, "volume": volume, "auto_stop": auto_stop, "auto_target": auto_target}


def _looks_like_setup(text: str) -> bool:
    import re

    return re.search(r"\b(entry|stop|stops|sl|tp|target|take profit)\b", text, re.I) is not None


def watch_setups(db: Session, accounts: list[Account]) -> None:
    rows = db.scalars(select(SetupWatch).where(SetupWatch.status == "watching")).all()
    by_id = {account.id: account for account in accounts}
    for row in rows:
        account = by_id.get(row.account_id) if row.account_id else None
        if account is None:
            account = _quote_account(db, row.organization_id)
            if account is not None and row.account_id is None:
                row.account_id = account.id
        if account is None or account.connection_method != "metaapi":
            continue
        price = _touch_price(db, account, row)
        if price is None or not _reached(row.side, price, row.entry):
            continue
        if not row.order_sent:
            _send_limit(db, row)
        if row.notified:
            row.status = "reached"
            continue
        _notify(db, row, price)
        row.notified = True
        row.status = "reached"
    db.flush()


def _arm(db: Session, organization_id: UUID, chat_id: str, found: dict) -> str:
    entry = found["entry"]
    existing = db.scalar(
        select(SetupWatch).where(
            SetupWatch.organization_id == organization_id,
            SetupWatch.status == "watching",
            SetupWatch.symbol == found["symbol"],
            SetupWatch.side == found["side"],
            SetupWatch.entry == entry,
        )
    )
    if existing is not None:
        return f"Already watching {found['side']} {found['symbol']} at {_plain(entry)}."
    account = _trade_account(db, organization_id)
    row = SetupWatch(
        organization_id=organization_id,
        account_id=None if account is None else account.id,
        chat_id=str(chat_id or ""),
        symbol=found["symbol"],
        side=found["side"],
        entry=entry,
        stop_loss=found["stop_loss"],
        take_profit=found["take_profit"],
        volume=found["volume"],
        status="watching",
    )
    db.add(row)
    db.flush()
    calculated = []
    if found.get("auto_stop"):
        calculated.append("the stop is 100 pips")
    if found.get("auto_target"):
        calculated.append("the target is 2R")
    prefix = f"No {'stop' if found.get('auto_stop') else 'target'} was given, so {' and '.join(calculated)}. " if calculated else ""
    return prefix + _arm_reply(db, row, account)


def _arm_reply(db: Session, row: SetupWatch, account: Account | None) -> str:
    if account is None:
        row.note = "DeepSeek trading is off"
        return (
            f"Watching {row.side} {row.symbol} at {_plain(row.entry)}. "
            f"Stop {_plain(row.stop_loss)}, target {_plain(row.take_profit)}. "
            "I did not send the limit. Turn on Allow DeepSeek to trade on one account and I will enter when price reaches it."
        )
    sent, note = _send_limit(db, row)
    if sent:
        return (
            f"Limit set. {row.side} {row.symbol} at {_plain(row.entry)}, "
            f"stop {_plain(row.stop_loss)}, target {_plain(row.take_profit)}. "
            "I will notify you when price reaches the entry."
        )
    return (
        f"Watching {row.side} {row.symbol} at {_plain(row.entry)}, "
        f"stop {_plain(row.stop_loss)}, target {_plain(row.take_profit)}. "
        f"The limit was not sent. {note} I will try again when price reaches the entry if trading is allowed."
    )


def _send_limit(db: Session, row: SetupWatch) -> tuple[bool, str]:
    if row.order_sent:
        return True, row.note
    if row.stop_loss is None or row.take_profit is None:
        row.note = "Entry, stop, and target are required"
        return False, row.note
    account = _trade_account(db, row.organization_id)
    if account is None:
        row.note = "DeepSeek trading is off"
        return False, row.note
    user = db.scalar(select(User).where(User.organization_id == row.organization_id, User.is_active.is_(True)).order_by(User.created_at))
    if user is None:
        row.note = "No active user"
        return False, row.note
    from app.services.order_service import OrderError, place_order

    payload = {
        "action": "limit",
        "symbol": row.symbol,
        "side": row.side,
        "volume": row.volume,
        "price": row.entry,
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "source": "Telegram",
    }
    try:
        result = place_order(db, user, account, payload, actor="ai")
    except OrderError as exc:
        row.note = exc.detail[:300]
        return False, row.note
    row.account_id = account.id
    row.note = str(result.get("message") or "")[:300]
    if result.get("sent"):
        row.order_sent = True
        return True, row.note
    return False, row.note or "The limit was not sent"


def _touch_price(db: Session, account: Account, row: SetupWatch) -> Decimal | None:
    from app.services.order_service import OrderError, read_price

    try:
        quote = read_price(db, account, row.symbol)
    except OrderError:
        return None
    except Exception:
        logger.warning("setup_watch_price_failed")
        return None
    raw = quote.get("ask") if row.side == "buy" else quote.get("bid")
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def _reached(side: str, price: Decimal, entry: Decimal) -> bool:
    if side == "buy":
        return price <= entry
    return price >= entry


def _notify(db: Session, row: SetupWatch, price: Decimal) -> None:
    from app.services.alert_service import TelegramError, _telegram, _telegram_secret

    if row.order_sent:
        text = (
            f"Price reached {_plain(row.entry)} on {row.symbol}. Now {_plain(price)}. "
            f"The {row.side} limit is working, stop {_plain(row.stop_loss)}, target {_plain(row.take_profit)}."
        )
    else:
        text = (
            f"Price reached {_plain(row.entry)} on {row.symbol}. Now {_plain(price)}. "
            f"I did not enter. {row.note or 'Allow DeepSeek to trade on one account.'}"
        )
    saved = _telegram_secret(db, row.organization_id)
    token = str(saved.get("bot_token") or "")
    chat_id = row.chat_id or str(saved.get("chat_id") or "")
    if not token or not chat_id:
        return
    try:
        _telegram(token, "sendMessage", {"chat_id": chat_id, "text": text[:3900]})
    except TelegramError:
        logger.warning("setup_watch_notify_failed")


def _trade_account(db: Session, organization_id: UUID) -> Account | None:
    rows = db.scalars(
        select(Account).where(Account.organization_id == organization_id, Account.connection_method == "metaapi", Account.ai_trading_enabled.is_(True))
    ).all()
    if len(rows) != 1:
        return None
    return rows[0]


def _quote_account(db: Session, organization_id: UUID) -> Account | None:
    enabled = _trade_account(db, organization_id)
    if enabled is not None:
        return enabled
    rows = db.scalars(select(Account).where(Account.organization_id == organization_id, Account.connection_method == "metaapi")).all()
    if len(rows) == 1:
        return rows[0]
    return None


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

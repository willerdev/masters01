"""Remind the bound Telegram chat every 5 minutes while a limit has no stop."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account, NakedLimit

logger = logging.getLogger(__name__)

_INTERVAL = timedelta(minutes=5)


def remind_naked_limits(db: Session) -> None:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(NakedLimit)).all()
    books: dict = {}
    for row in rows:
        last = row.last_reminded_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is not None and now - last < _INTERVAL:
            continue
        account = db.get(Account, row.account_id)
        if account is None or account.connection_method != "metaapi":
            continue
        state = _state(db, account, row, books)
        if state == "unknown":
            continue
        if state in {"gone", "protected"}:
            db.delete(row)
            continue
        _notify(db, row)
        row.last_reminded_at = now
    db.flush()


def _state(db: Session, account: Account, row: NakedLimit, books: dict) -> str:
    if account.id not in books:
        books[account.id] = _load(db, account)
    book = books[account.id]
    if book is None:
        return "unknown"
    orders, positions = book
    order = _match_order(orders, row)
    if order is not None:
        ticket = str(order.get("id") or order.get("orderId") or "").strip()
        if ticket:
            row.ticket = ticket
        if _positive(order.get("stopLoss") if "stopLoss" in order else order.get("stop_loss")):
            return "protected"
        return "open"
    position = _match_position(positions, row)
    if position is None:
        return "gone"
    row.ticket = position.ticket
    if position.stop_loss is not None and position.stop_loss > 0:
        return "protected"
    return "open"


def _load(db: Session, account: Account):
    from app.connectors.metaapi import MetaApiConnector
    from app.services.account_service import load_credentials

    try:
        credentials = load_credentials(db, account.id)
        connector = MetaApiConnector()
        return connector.fetch_orders(credentials), connector.fetch_positions(credentials)
    except Exception:
        logger.warning("naked_limit_book_failed")
        return None


def _match_order(orders: list[dict], row: NakedLimit) -> dict | None:
    active = [item for item in orders if _active(item)]
    if row.ticket:
        for item in active:
            ticket = str(item.get("id") or item.get("orderId") or "")
            if ticket == row.ticket:
                return item
        return None
    for item in active:
        if str(item.get("symbol") or "") != row.symbol:
            continue
        if _order_side(item) != row.side:
            continue
        price = _decimal(item.get("openPrice") if item.get("openPrice") is not None else item.get("open_price"))
        if price is not None and _near(price, row.entry):
            return item
    return None


def _match_position(positions, row: NakedLimit):
    if row.ticket:
        for item in positions:
            if item.ticket == row.ticket:
                return item
    found = [
        item
        for item in positions
        if item.symbol == row.symbol and item.side == row.side and _near(item.entry_price, row.entry)
    ]
    if len(found) == 1:
        return found[0]
    same_volume = [item for item in found if item.volume == row.volume]
    if len(same_volume) == 1:
        return same_volume[0]
    return None


def _active(item: dict) -> bool:
    state = str(item.get("state") or "").upper()
    return not any(word in state for word in ("CANCEL", "REJECT", "EXPIR"))


def _order_side(item: dict) -> str:
    text = str(item.get("type") or item.get("side") or "").lower()
    if "buy" in text:
        return "buy"
    if "sell" in text:
        return "sell"
    return ""


def _notify(db: Session, row: NakedLimit) -> None:
    from app.services.alert_service import TelegramError, _telegram, _telegram_secret

    side = "Buy" if row.side == "buy" else "Sell"
    rejected = ""
    if row.ignored_stop is not None:
        rejected = f" The stop {_plain(row.ignored_stop)} was rejected."
    text = (
        f"{side} limit {row.symbol} at {_plain(row.entry)} still has no stop loss.{rejected} "
        "Set a stop or delete the order. This repeats every 5 minutes until then."
    )
    saved = _telegram_secret(db, row.organization_id)
    token = str(saved.get("bot_token") or "")
    chat_id = str(saved.get("chat_id") or "")
    if not token or not chat_id:
        return
    try:
        _telegram(token, "sendMessage", {"chat_id": chat_id, "text": text[:3900]})
    except TelegramError:
        logger.warning("naked_limit_notify_failed")


def _positive(value) -> bool:
    number = _decimal(value)
    return number is not None and number > 0


def _decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _near(left: Decimal, right: Decimal) -> bool:
    if left <= 0 or right <= 0:
        return False
    return abs(left - right) <= max(Decimal("0.0001"), abs(right) * Decimal("0.002"))


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

"""Watch open trades on the live price loop and announce each milestone once."""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account, Position, TradeMilestone, User

logger = logging.getLogger(__name__)

_PROFIT_R = Decimal("0.15")
_MOVED_R = Decimal("0.25")
_ENTRY_R = Decimal("0.08")
_LEVELS = ((1, "rr1"), (2, "rr2"), (3, "rr3"), (4, "rr4"))
_fail_until: dict[str, float] = {}
_breakeven_tried: set[str] = set()


def watch_open_trades(db: Session, accounts: list[Account]) -> None:
    for account in accounts:
        try:
            _watch_account(db, account)
        except Exception:
            logger.exception("trade_watch_failed")


def pending_codes(side: str, entry: Decimal, current: Decimal, stop: Decimal | None, profit: Decimal, seen: set[str]) -> list[str]:
    codes: list[str] = []
    reward = _reward_r(side, entry, current, stop)
    if reward is None:
        if profit > 0 and "profit" not in seen:
            codes.append("profit")
        if profit != 0 and "moved" not in seen:
            codes.append("moved")
        if "moved" in seen and "entry" not in seen and _near_entry(entry, current):
            codes.append("entry")
        return codes
    if reward >= _PROFIT_R and "profit" not in seen:
        codes.append("profit")
    if abs(reward) >= _MOVED_R and "moved" not in seen:
        codes.append("moved")
    if "moved" in seen and abs(reward) <= _ENTRY_R and "entry" not in seen:
        codes.append("entry")
    for level, code in _LEVELS:
        if reward >= level and code not in seen:
            codes.append(code)
    return codes


def format_update(position: Position, codes: list[str]) -> str:
    side = "Buy" if str(position.side).lower() == "buy" else "Sell"
    lines = [f"{side} {position.symbol} {_plain(position.volume)} ticket {position.ticket}"]
    price = f"Price {_plain(position.current_price)} · entry {_plain(position.entry_price)}"
    if position.stop_loss is not None and position.stop_loss > 0:
        price += f" · stop {_plain(position.stop_loss)}"
    lines.append(price)
    lines.append(f"Floating {_money(position.profit)}")
    source = (position.comment or position.strategy or "").strip()
    if source:
        lines.append(f"Source {source}")
    reward = _reward_r(position.side, position.entry_price, position.current_price, _stop(position.stop_loss))
    if reward is not None and any(code.startswith("rr") for code in codes):
        lines.append(f"Reward is {_plain(reward.quantize(Decimal('0.1')))} times the risk.")
    if "profit" in codes and not any(code.startswith("rr") for code in codes):
        lines.append("The trade is in profit.")
    if "entry" in codes:
        lines.append("Price is back at the entry.")
    if "rr1" in codes:
        lines.append("Reward has reached 1:1. Take partials and move the stop to breakeven.")
    for level, code in _LEVELS:
        if level == 1 or code not in codes:
            continue
        lines.append(f"Reward has reached {level}:1.")
    return "\n".join(lines)


def _watch_account(db: Session, account: Account) -> None:
    rows = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    open_tickets = {row.ticket for row in rows}
    stored = db.scalars(select(TradeMilestone).where(TradeMilestone.account_id == account.id)).all()
    seen_by_ticket: dict[str, set[str]] = {}
    for item in stored:
        if item.ticket not in open_tickets:
            db.delete(item)
            continue
        seen_by_ticket.setdefault(item.ticket, set()).add(item.code)
    for row in rows:
        seen = seen_by_ticket.get(row.ticket, set())
        codes = pending_codes(row.side, row.entry_price, row.current_price, _stop(row.stop_loss), row.profit or Decimal("0"), seen)
        if not codes:
            continue
        visible = [code for code in codes if code != "moved"]
        text = format_update(row, visible) if visible else ""
        if "rr1" in codes:
            note = _breakeven_once(db, account, row)
            if note:
                text = f"{text}\n{note}" if text else note
        if text and not _deliver(db, account, text):
            continue
        for code in codes:
            db.add(TradeMilestone(account_id=account.id, ticket=row.ticket, code=code))
    db.flush()


def _breakeven_once(db: Session, account: Account, row: Position) -> str:
    """At 1R, move a stop that is still on the loss side to the entry. Each ticket is tried once per process."""
    stop = _stop(row.stop_loss)
    if stop is None:
        return ""
    buy = str(row.side).lower() == "buy"
    if (buy and stop >= row.entry_price) or (not buy and stop <= row.entry_price):
        return ""
    key = f"{account.id}:{row.ticket}"
    if key in _breakeven_tried:
        return ""
    _breakeven_tried.add(key)
    from app.services.order_service import OrderError, place_order

    user = db.scalar(select(User).where(User.organization_id == account.organization_id, User.is_active.is_(True)).order_by(User.created_at))
    if user is None:
        return "The stop was not moved to the entry. No active user."
    try:
        result = place_order(db, user, account, {"action": "breakeven", "ticket": row.ticket}, actor="ai")
    except OrderError as exc:
        return f"The stop was not moved to the entry. {exc.detail}"
    except Exception:
        logger.warning("trade_watch_breakeven_failed")
        return "The stop was not moved to the entry. The broker did not answer."
    if result.get("sent"):
        return f"The stop was moved to the entry at {_plain(row.entry_price)}."
    reason = str(result.get("message") or "The broker refused it.")
    return f"The stop was not moved to the entry. {reason}"


def _deliver(db: Session, account: Account, text: str) -> bool:
    from app.services.alert_service import TelegramError, _deliver_in_app, _telegram, _telegram_secret
    from app.models.entities import Alert

    saved = _telegram_secret(db, account.organization_id)
    token = str(saved.get("bot_token") or "")
    chat_id = str(saved.get("chat_id") or "")
    if token and chat_id:
        quiet = _fail_until.get(str(account.organization_id), 0)
        if time.monotonic() < quiet:
            return False
        try:
            result = _telegram(token, "sendMessage", {"chat_id": chat_id, "text": text[:3900]})
            if not result.get("ok"):
                raise TelegramError(502, "Telegram did not accept the trade update")
        except TelegramError:
            logger.warning("trade_watch_telegram_failed")
            _fail_until[str(account.organization_id)] = time.monotonic() + 60
            return False
    title = text.split("\n", 1)[0][:200]
    alert = Alert(
        organization_id=account.organization_id,
        account_id=account.id,
        alert_type="trade_update",
        severity="info",
        title=title,
        body=text,
        dedupe_key="",
        status="sent",
    )
    db.add(alert)
    db.flush()
    users = db.scalars(select(User).where(User.organization_id == account.organization_id, User.is_active.is_(True))).all()
    for user in users:
        _deliver_in_app(db, alert, user)
    return True


def _reward_r(side: str, entry: Decimal, current: Decimal, stop: Decimal | None) -> Decimal | None:
    if stop is None or entry <= 0 or current <= 0:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    move = current - entry if str(side).lower() == "buy" else entry - current
    return move / risk


def _stop(value: Decimal | None) -> Decimal | None:
    if value is None or value <= 0:
        return None
    return value


def _near_entry(entry: Decimal, current: Decimal) -> bool:
    band = max(abs(entry) * Decimal("0.0005"), Decimal("0.5"))
    return abs(current - entry) <= band


def _plain(value: Decimal) -> str:
    text = format(Decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _money(value: Decimal) -> str:
    number = Decimal(value).quantize(Decimal("0.01"))
    sign = "+" if number > 0 else ""
    return f"{sign}{number}"

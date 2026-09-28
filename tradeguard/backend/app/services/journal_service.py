from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.registry import connector_for
from app.models.entities import Account, ClosedTrade, Position
from app.services.account_service import load_credentials


def account_journal(db: Session, account: Account) -> dict:
    error = _sync_terminal_history(db, account)
    closed = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account.id).order_by(ClosedTrade.close_time.asc())).all()
    days: dict[str, dict] = {}
    sources_totals: dict[str, dict] = {}
    for trade in closed:
        moment = trade.close_time or trade.open_time
        if moment is None:
            continue
        key = _day(account, moment).isoformat()
        bucket = days.setdefault(key, {"date": key, "net": Decimal("0"), "trades": []})
        net = _net(trade.profit, trade.swap, trade.commission)
        bucket["net"] += net
        bucket["trades"].append(_closed_row(trade, net))
        _add_source(sources_totals, trade.strategy or trade.comment, net)
    today = _day(account, datetime.now(timezone.utc)).isoformat()
    for position in db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all():
        bucket = days.setdefault(today, {"date": today, "net": Decimal("0"), "trades": []})
        floating = position.profit or Decimal("0")
        bucket["net"] += floating
        bucket["trades"].append(
            {
                "ticket": position.ticket,
                "symbol": position.symbol,
                "direction": position.side,
                "lot": _plain(position.volume),
                "entry": _plain(position.entry_price),
                "close_price": None,
                "profit": f"{floating:.2f}",
                "status": "open",
                "close_time": None,
                "source": (position.strategy or position.comment or "").strip(),
            }
        )
        _add_source(sources_totals, position.strategy or position.comment, floating)
    ordered = []
    profitable = loss = even = 0
    net_total = Decimal("0")
    trade_count = 0
    for key in sorted(days, reverse=True):
        bucket = days[key]
        result = _result(bucket["net"])
        if result == "profit":
            profitable += 1
        elif result == "loss":
            loss += 1
        else:
            even += 1
        net_total += bucket["net"]
        trade_count += len(bucket["trades"])
        ordered.append(
            {
                "date": bucket["date"],
                "net": f"{bucket['net']:.2f}",
                "result": result,
                "trade_count": len(bucket["trades"]),
                "trades": list(reversed(bucket["trades"])),
            }
        )
    return {
        "account_id": str(account.id),
        "account_name": account.display_name,
        "currency": account.currency,
        "error": error,
        "summary": {
            "profitable_days": profitable,
            "loss_days": loss,
            "even_days": even,
            "net": f"{net_total:.2f}",
            "trades": trade_count,
        },
        "days": ordered,
        "sources": _source_rows(sources_totals),
    }


def _sync_terminal_history(db: Session, account: Account) -> str:
    if account.connection_method != "metaapi":
        return ""
    connector = connector_for("metaapi")
    fetch = getattr(connector, "fetch_deals", None)
    if fetch is None:
        return ""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    try:
        deals = fetch(load_credentials(db, account.id), start, end)
    except Exception as exc:  # noqa: BLE001
        text = str(exc).strip()
        if not text or any(word in text.lower() for word in ("token", "password", "auth-token")):
            return "Closed trades could not be read from the terminal"
        return text[:180]
    sources = _opening_comments(deals)
    for deal in deals:
        if _opening_only(deal):
            continue
        _upsert_deal(db, account, deal, sources)
    db.flush()
    return ""


def _opening_comments(deals: list) -> dict[str, str]:
    found: dict[str, str] = {}
    for deal in deals:
        if not isinstance(deal, dict):
            continue
        position_id = str(deal.get("positionId") or "").strip()
        comment = str(deal.get("comment") or "").strip()
        if not position_id or not comment:
            continue
        entry = str(deal.get("entryType") or "")
        if entry in {"DEAL_ENTRY_IN", "ENTRY_IN"} or position_id not in found:
            found[position_id] = comment[:80]
    return found


def _opening_only(deal: object) -> bool:
    if not isinstance(deal, dict):
        return False
    return str(deal.get("entryType") or "") in {"DEAL_ENTRY_IN", "ENTRY_IN"}


def _deal_source(deal: dict, sources: dict[str, str]) -> str:
    own = str(deal.get("comment") or "").strip()
    opened = sources.get(str(deal.get("positionId") or "").strip(), "")
    entry = str(deal.get("entryType") or "")
    if entry in {"DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY", "ENTRY_OUT"} and opened:
        return opened
    return own or opened


def _upsert_deal(db: Session, account: Account, deal: dict, sources: dict[str, str] | None = None) -> None:
    if not isinstance(deal, dict):
        return
    kind = str(deal.get("type") or "")
    if "BUY" not in kind and "SELL" not in kind:
        return
    symbol = str(deal.get("symbol") or "").strip()
    ticket = str(deal.get("id") or deal.get("ticket") or "").strip()
    if not symbol or not ticket:
        return
    moment = _parse_time(deal.get("time") or deal.get("brokerTime"))
    row = db.scalar(select(ClosedTrade).where(ClosedTrade.account_id == account.id, ClosedTrade.ticket == ticket))
    if row is None:
        row = ClosedTrade(
            account_id=account.id,
            ticket=ticket,
            symbol=symbol,
            side="buy" if "BUY" in kind else "sell",
            volume=_decimal(deal.get("volume"), "0"),
            entry_price=_decimal(deal.get("price"), "0"),
            close_price=_decimal(deal.get("price"), "0"),
            profit=_decimal(deal.get("profit"), "0"),
        )
        db.add(row)
    row.symbol = symbol
    row.side = "buy" if "BUY" in kind else "sell"
    row.volume = _decimal(deal.get("volume"), "0")
    row.close_price = _decimal(deal.get("price"), "0")
    row.profit = _decimal(deal.get("profit"), "0")
    row.swap = _decimal(deal.get("swap"), "0")
    row.commission = _decimal(deal.get("commission"), "0")
    row.close_time = moment
    row.open_time = moment
    row.magic_number = int(deal.get("magic") or 0)
    source = _deal_source(deal, sources or {})
    if source:
        row.comment = source[:200]
        row.strategy = source[:80]


def _add_source(totals: dict[str, dict], name: str, net: Decimal) -> None:
    label = str(name or "").strip() or "Unknown"
    bucket = totals.setdefault(label, {"source": label, "net": Decimal("0"), "trades": 0})
    bucket["net"] += net
    bucket["trades"] += 1


def _source_rows(totals: dict[str, dict]) -> list[dict]:
    rows = []
    for bucket in sorted(totals.values(), key=lambda item: item["net"], reverse=True):
        rows.append(
            {
                "source": bucket["source"],
                "net": f"{bucket['net']:.2f}",
                "trades": bucket["trades"],
                "result": _result(bucket["net"]),
            }
        )
    return rows


def _closed_row(trade: ClosedTrade, net: Decimal) -> dict:
    return {
        "ticket": trade.ticket,
        "symbol": trade.symbol,
        "direction": trade.side,
        "lot": _plain(trade.volume),
        "entry": _plain(trade.entry_price),
        "close_price": _plain(trade.close_price),
        "profit": f"{net:.2f}",
        "status": "closed",
        "close_time": None if trade.close_time is None else trade.close_time.isoformat(),
        "source": (trade.strategy or trade.comment or "").strip(),
    }


def _day(account: Account, moment: datetime):
    try:
        zone = ZoneInfo(account.trading_day_timezone or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone).date()


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _decimal(value: object, default: str) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except Exception:  # noqa: BLE001
        return Decimal(default)


def _net(*parts: Decimal | None) -> Decimal:
    total = Decimal("0")
    for part in parts:
        total += part or Decimal("0")
    return total


def _result(net: Decimal) -> str:
    if net > 0:
        return "profit"
    if net < 0:
        return "loss"
    return "even"


def _plain(number: Decimal | None) -> str:
    text = format(number or Decimal("0"), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

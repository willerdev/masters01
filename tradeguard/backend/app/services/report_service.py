from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account, AccountState, ClosedTrade, DailyStatistic, Position, RiskViolation, User
from app.services.account_service import visible_account_query
from app.services.health_service import account_health
from tradeguard_risk.behavior import measure_behavior
from tradeguard_risk.overtrading import TradeSample
from tradeguard_risk.performance import performance_stats


def _window(period: str) -> date:
    today = datetime.now(timezone.utc).date()
    if period == "weekly":
        return today - timedelta(days=7)
    if period == "monthly":
        return today - timedelta(days=30)
    return today


def build_report(db: Session, user: User, roles: list[str], *, period: str, kind: str) -> dict:
    start = _window(period)
    accounts = db.scalars(visible_account_query(db, user, roles)).all()
    sections = []
    for account in accounts:
        state = db.get(AccountState, account.id)
        trades = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account.id)).all()
        in_period = [trade for trade in trades if trade.close_time is None or trade.close_time.date() >= start]
        profits = [trade.profit for trade in in_period]
        stats = performance_stats(profits, [state.equity] if state else [])
        violations = db.scalars(select(RiskViolation).where(RiskViolation.account_id == account.id)).all()
        open_risk = sum((position.risk_amount or Decimal("0") for position in db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()), Decimal("0"))
        equity = state.equity if state else Decimal("0")
        samples = [
            TradeSample(trade.symbol, trade.volume, trade.open_time or trade.close_time, trade.close_time, trade.profit)
            for trade in in_period
            if trade.open_time or trade.close_time
        ]
        behavior = measure_behavior(samples, datetime.now(timezone.utc))
        health = account_health(db, account)
        daily = db.scalars(select(DailyStatistic).where(DailyStatistic.account_id == account.id, DailyStatistic.trading_date >= start)).all()
        sections.append(
            {
                "account": account.display_name,
                "account_number": account.account_number,
                "balance": f"{(state.balance if state else 0):.2f}",
                "equity": f"{equity:.2f}",
                "pnl": f"{sum((row.end_equity - row.start_equity for row in daily), Decimal('0')):.2f}",
                "drawdown": _drawdown(state),
                "trades": len(in_period),
                "win_rate": None if stats.win_rate is None else f"{stats.win_rate:.4f}",
                "profit_factor": None if stats.profit_factor is None else f"{stats.profit_factor:.4f}",
                "risk_utilization": "0.00" if equity <= 0 else f"{(open_risk / equity * Decimal('100')):.2f}",
                "violations": len([row for row in violations if row.opened_at.date() >= start]),
                "overtrading": behavior["features"],
                "account_health": health["status"],
                "health_reasons": health["reasons"],
                "major_events": [f"{row.code}: {row.message}" for row in violations if row.opened_at.date() >= start][:12],
            }
        )
    return {"period": period, "kind": kind, "generated_at": datetime.now(timezone.utc).isoformat(), "accounts": sections}


def _drawdown(state: AccountState | None) -> str:
    if state is None or not state.peak_equity or state.peak_equity <= 0 or state.equity >= state.peak_equity:
        return "0.00"
    return f"{((state.peak_equity - state.equity) / state.peak_equity * Decimal('100')):.2f}"


def report_csv(report: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["account", "balance", "equity", "pnl", "drawdown", "trades", "win_rate", "profit_factor", "risk_utilization", "violations", "health"])
    for row in report["accounts"]:
        writer.writerow([row["account"], row["balance"], row["equity"], row["pnl"], row["drawdown"], row["trades"], row["win_rate"], row["profit_factor"], row["risk_utilization"], row["violations"], row["account_health"]])
    return buffer.getvalue()


def report_pdf(report: dict) -> bytes:
    lines = [f"TRADEGUARD {report['kind'].replace('_', ' ').upper()} REPORT", f"Period: {report['period']}", f"Generated: {report['generated_at']}", ""]
    for row in report["accounts"]:
        lines.append(row["account"])
        lines.append(f"Balance {row['balance']}  Equity {row['equity']}  P/L {row['pnl']}")
        lines.append(f"Drawdown {row['drawdown']}%  Trades {row['trades']}  Win rate {row['win_rate']}  Profit factor {row['profit_factor']}")
        lines.append(f"Risk utilization {row['risk_utilization']}%  Violations {row['violations']}  Health {row['account_health']}")
        lines.append("")
    if len(lines) < 8:
        lines.append("No accounts in scope.")
    return _pdf(lines)


def _pdf(lines: list[str]) -> bytes:
    escaped = []
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        escaped.append(safe[:110])
    commands = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for line in escaped[:48]:
        commands.append(f"({line}) '")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")
    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n")
    objects.append(b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n")
    objects.append(f"4 0 obj<< /Length {len(stream)} >>stream\n".encode() + stream + b"\nendstream\nendobj\n")
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)

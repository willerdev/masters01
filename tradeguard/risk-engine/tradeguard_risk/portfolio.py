from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from tradeguard_risk.drawdown import current_drawdown_pct
from tradeguard_risk.money import D, quantize_money


@dataclass
class PortfolioPosition:
    symbol: str
    notional: Decimal
    side: str = "buy"


@dataclass
class PortfolioAccount:
    account_id: str
    name: str
    balance: Decimal
    equity: Decimal
    peak_equity: Decimal
    open_risk: Decimal
    positions: list[PortfolioPosition] = field(default_factory=list)


def _pair_overlap(left: str, right: str) -> Decimal:
    if left == right:
        return Decimal("1")
    if len(left) >= 6 and len(right) >= 6:
        left_ccy = {left[:3], left[3:6]}
        right_ccy = {right[:3], right[3:6]}
        shared = left_ccy & right_ccy
        if len(shared) == 2:
            return Decimal("1")
        if len(shared) == 1:
            return Decimal("0.50")
    return Decimal("0")


def portfolio_snapshot(accounts: list[PortfolioAccount]) -> dict:
    balance = sum((D(account.balance) for account in accounts), Decimal("0"))
    equity = sum((D(account.equity) for account in accounts), Decimal("0"))
    peak = sum((D(account.peak_equity) for account in accounts), Decimal("0"))
    open_risk = sum((D(account.open_risk) for account in accounts), Decimal("0"))
    by_symbol: dict[str, Decimal] = {}
    for account in accounts:
        for position in account.positions:
            by_symbol[position.symbol] = by_symbol.get(position.symbol, Decimal("0")) + abs(D(position.notional))
    exposure = sum(by_symbol.values(), Decimal("0"))
    symbols = list(by_symbol)
    pairs = []
    for index, left in enumerate(symbols):
        for right in symbols[index + 1 :]:
            overlap = _pair_overlap(left, right)
            if overlap > 0:
                pairs.append(
                    {
                        "left": left,
                        "right": right,
                        "overlap": f"{overlap:.2f}",
                        "combined_notional": f"{(by_symbol[left] + by_symbol[right]):.2f}",
                    }
                )
    return {
        "accounts": len(accounts),
        "total_capital": f"{quantize_money(balance):.2f}",
        "total_equity": f"{quantize_money(equity):.2f}",
        "total_exposure": f"{quantize_money(exposure):.2f}",
        "total_open_risk": f"{quantize_money(open_risk):.2f}",
        "combined_drawdown": f"{current_drawdown_pct(peak, equity):.2f}",
        "account_drawdown": [
            {
                "account_id": account.account_id,
                "name": account.name,
                "balance": f"{D(account.balance):.2f}",
                "equity": f"{D(account.equity):.2f}",
                "drawdown": f"{current_drawdown_pct(account.peak_equity, account.equity):.2f}",
                "open_risk": f"{D(account.open_risk):.2f}",
            }
            for account in accounts
        ],
        "symbol_exposure": [{"symbol": symbol, "notional": f"{value:.2f}"} for symbol, value in sorted(by_symbol.items())],
        "correlation_exposure": pairs,
    }

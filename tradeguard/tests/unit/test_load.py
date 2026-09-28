from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradeguard_risk.behavior import measure_behavior
from tradeguard_risk.portfolio import PortfolioAccount, portfolio_snapshot
from tradeguard_risk.overtrading import TradeSample


def test_portfolio_of_100_accounts_and_1000_trades():
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    accounts = [
        PortfolioAccount(str(index), f"A{index}", Decimal("10000"), Decimal("9900"), Decimal("10000"), Decimal("25"))
        for index in range(100)
    ]
    book = portfolio_snapshot(accounts)
    assert book["accounts"] == 100
    assert book["total_capital"] == "1000000.00"
    trades = [
        TradeSample("EURUSD" if index % 3 else "XAUUSD", Decimal("0.10"), now - timedelta(minutes=index), now - timedelta(minutes=index - 1), Decimal("-1"))
        for index in range(1, 1001)
    ]
    measured = measure_behavior(trades, now)
    assert measured["features"]["daily_trade_count"] > 100

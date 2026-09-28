from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradeguard_risk.behavior import measure_behavior
from tradeguard_risk.health import HealthInput, assess_health
from tradeguard_risk.overtrading import TradeSample
from tradeguard_risk.portfolio import PortfolioAccount, PortfolioPosition, portfolio_snapshot
from tradeguard_risk.simulation import simulate_trade
from tradeguard_risk.types import SymbolSpec
from app.core.rate_limit import WindowLimiter
from app.services.report_service import report_pdf


NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
EUR = SymbolSpec("EURUSD", Decimal("0.00001"), Decimal("1"), Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "USD")


def test_health_reasons_are_measurable():
    status, reasons = assess_health(
        HealthInput(
            risk_utilization_pct=Decimal("85"),
            drawdown_pct=Decimal("8"),
            max_drawdown_pct=Decimal("10"),
            margin_level=Decimal("180"),
            connection_status="connected",
            trades_today=9,
            max_trades_per_day=10,
        )
    )
    assert status == "HIGH_RISK"
    assert {reason.code for reason in reasons} >= {"DRAWDOWN_ELEVATED", "RISK_UTILIZATION"}
    assert all(reason.measured and reason.threshold for reason in reasons)


def test_disconnected_account_is_critical():
    status, reasons = assess_health(HealthInput(risk_utilization_pct=Decimal("0"), drawdown_pct=Decimal("0"), max_drawdown_pct=Decimal("10"), margin_level=None, connection_status="disconnected"))
    assert status == "CRITICAL"
    assert reasons[0].code == "CONNECTION_DOWN"


def test_simulator_answers_the_three_questions():
    result = simulate_trade(balance=Decimal("10000"), risk_percent=Decimal("1"), stop_loss=Decimal("1.098"), symbol="EURUSD", entry_price=Decimal("1.10000"), lot_size=Decimal("0.50"), spec=EUR, take_profit=Decimal("1.104"))
    assert Decimal(result["potential_loss"]) == Decimal("100.00")
    assert Decimal(result["loss_streak"]["equity_after"]) < Decimal("10000")
    assert result["daily_loss"]["loss_amount"] == "300.00"
    assert Decimal(result["risk_change"]["loss_budget_to"]) == Decimal("200.00")
    assert result["risk_reward"] == "2.00"


def test_portfolio_combines_accounts():
    book = portfolio_snapshot(
        [
            PortfolioAccount("a", "A", Decimal("10000"), Decimal("9800"), Decimal("10000"), Decimal("100"), [PortfolioPosition("EURUSD", Decimal("10000"))]),
            PortfolioAccount("b", "B", Decimal("25000"), Decimal("25000"), Decimal("25000"), Decimal("50"), [PortfolioPosition("EURUSD", Decimal("5000"))]),
            PortfolioAccount("c", "C", Decimal("50000"), Decimal("49000"), Decimal("50000"), Decimal("200"), []),
        ]
    )
    assert book["total_capital"] == "85000.00"
    assert book["total_equity"] == "83800.00"
    assert Decimal(book["combined_drawdown"]) > 0
    assert book["symbol_exposure"][0]["symbol"] == "EURUSD"
    assert book["correlation_exposure"] == []


def test_behavior_describes_observations():
    trades = []
    for index in range(12):
        opened = NOW - timedelta(minutes=30 - index)
        trades.append(TradeSample("EURUSD", Decimal("0.1") * (index + 1), opened, opened + timedelta(seconds=20), Decimal("-5"), stop_loss_hit=True))
    measured = measure_behavior(trades, NOW)
    assert measured["features"]["daily_trade_count"] == 12
    assert "daily_trade_count" in measured["threshold_breaches"]
    assert measured["observations"]
    assert "revenge" not in " ".join(measured["observations"]).lower()


def test_pdf_starts_with_header():
    blob = report_pdf({"kind": "risk", "period": "daily", "generated_at": "2026-09-26T00:00:00Z", "accounts": []})
    assert blob.startswith(b"%PDF-1.4")


def test_login_limiter_blocks_after_the_window():
    limiter = WindowLimiter()
    for _ in range(5):
        assert limiter.hit("ip", limit=5, window_seconds=60) is False
    assert limiter.hit("ip", limit=5, window_seconds=60) is True

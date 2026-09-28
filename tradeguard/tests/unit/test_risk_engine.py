from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from tradeguard_risk.decisions import evaluate_fail_closed, evaluate_proposed
from tradeguard_risk.drawdown import current_drawdown_pct, daily_loss_pct, max_drawdown_pct
from tradeguard_risk.overtrading import TradeSample, assess_overtrading
from tradeguard_risk.performance import performance_stats
from tradeguard_risk.quotes import quote_is_stale
from tradeguard_risk.sizing import suggest_volume
from tradeguard_risk.types import AccountRiskState, Decision, EffectiveRules, OvertradingState, ProposedOrder, SymbolSpec

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
EURUSD = SymbolSpec("EURUSD", Decimal("0.00001"), Decimal("1"), Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "USD")
USDJPY = SymbolSpec("USDJPY", Decimal("0.001"), Decimal("100"), Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "JPY", 3)
XAUUSD = SymbolSpec("XAUUSD", Decimal("0.01"), Decimal("1"), Decimal("100"), Decimal("0.01"), Decimal("50"), Decimal("0.01"), "USD", 2, "metal", "cfd")
US30 = SymbolSpec("US30", Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.1"), Decimal("100"), Decimal("0.1"), "USD", 1, "index", "cfd_index")


def _state(**kwargs) -> AccountRiskState:
    base = dict(
        equity=Decimal("10000"),
        balance=Decimal("10000"),
        margin=Decimal("0"),
        free_margin=Decimal("10000"),
        margin_level=None,
        day_start_equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        trades_today=0,
        consecutive_losses=0,
    )
    base.update(kwargs)
    return AccountRiskState(**base)


def test_eurusd_position_size_uses_tick_value():
    result = suggest_volume(Decimal("10000"), Decimal("1"), Decimal("1.10000"), Decimal("1.09800"), EURUSD)
    assert result.suggested_volume == Decimal("0.50")
    assert result.loss_per_lot == Decimal("200.00000000")


def test_usdjpy_converts_with_explicit_fx():
    # 20 pips = 0.200 price = 200 ticks. tick value 100 JPY. fx 0.0067 USD per JPY.
    result = suggest_volume(Decimal("10000"), Decimal("1"), Decimal("149.200"), Decimal("149.000"), USDJPY, Decimal("0.0067"))
    assert result.incomplete is False
    assert result.suggested_volume is not None
    assert result.suggested_volume < Decimal("1")


def test_gold_does_not_use_forex_contract():
    result = suggest_volume(Decimal("10000"), Decimal("1"), Decimal("2330"), Decimal("2328"), XAUUSD)
    # distance 2.00 / 0.01 = 200 ticks * $1 = $200 per lot. Budget $100 → 0.50 lots.
    assert result.loss_per_lot == Decimal("200.00000000")
    assert result.suggested_volume == Decimal("0.50")


def test_index_tick_is_one_point():
    result = suggest_volume(Decimal("10000"), Decimal("1"), Decimal("39000"), Decimal("38950"), US30)
    assert result.loss_per_lot == Decimal("50.00000000")
    assert result.suggested_volume == Decimal("2.0")


def test_missing_stop_is_unprotected():
    result = suggest_volume(Decimal("10000"), Decimal("1"), Decimal("1.1"), None, EURUSD)
    assert result.unprotected is True
    assert result.suggested_volume is None


def test_min_lot_above_budget_is_refused():
    tiny = SymbolSpec("EURUSD", Decimal("0.00001"), Decimal("1"), Decimal("100000"), Decimal("1"), Decimal("100"), Decimal("0.01"), "USD")
    result = suggest_volume(Decimal("10000"), Decimal("1"), Decimal("1.10000"), Decimal("1.09000"), tiny)
    assert result.reason == "min_lot_exceeds_risk_budget"


def test_daily_loss_and_drawdown():
    assert daily_loss_pct(Decimal("10000"), Decimal("9700")) == Decimal("3.00000000")
    assert daily_loss_pct(Decimal("10000"), Decimal("10100")) == Decimal("0")
    assert current_drawdown_pct(Decimal("11000"), Decimal("9900")) == Decimal("10.00000000")
    assert max_drawdown_pct([Decimal("100"), Decimal("120"), Decimal("90")]) == Decimal("25.00000000")


def test_exact_risk_limit_is_allowed_and_over_is_blocked():
    rules = EffectiveRules(max_lot=Decimal("5"))
    order = ProposedOrder("EURUSD", "buy", Decimal("0.50"), Decimal("1.10000"), Decimal("1.09800"))
    allowed = evaluate_proposed(_state(), rules, order, EURUSD, now=NOW)
    assert allowed.risk_percent == Decimal("1.00000000")
    assert allowed.decision in {Decision.ALLOW, Decision.WARNING}
    assert allowed.decision != Decision.BLOCK
    larger = ProposedOrder("EURUSD", "buy", Decimal("0.51"), Decimal("1.10000"), Decimal("1.09800"))
    blocked = evaluate_proposed(_state(), rules, larger, EURUSD, now=NOW)
    assert blocked.decision == Decision.BLOCK
    assert any(hit.code == "MAX_RISK_PER_TRADE" for hit in blocked.hits)


def test_daily_loss_limit_stops_the_account():
    result = evaluate_fail_closed(_state(equity=Decimal("9600")), EffectiveRules(), now=NOW)
    assert result.decision == Decision.EMERGENCY_STOP
    assert any(hit.code == "MAX_DAILY_LOSS" for hit in result.hits)


def test_drawdown_limit():
    result = evaluate_fail_closed(_state(equity=Decimal("8900"), peak_equity=Decimal("10000")), EffectiveRules(), now=NOW)
    assert result.decision == Decision.EMERGENCY_STOP


def test_trade_count_and_lot_and_spacing():
    rules = EffectiveRules()
    order = ProposedOrder("EURUSD", "buy", Decimal("0.10"), Decimal("1.10000"), Decimal("1.09800"))
    too_many = evaluate_proposed(_state(trades_today=10), rules, order, EURUSD, now=NOW)
    assert too_many.decision == Decision.BLOCK
    huge = ProposedOrder("EURUSD", "buy", Decimal("0.30"), Decimal("1.10000"), Decimal("1.09980"))
    assert evaluate_proposed(_state(), rules, huge, EURUSD, now=NOW).decision == Decision.BLOCK
    recent = evaluate_proposed(_state(last_entry_at=NOW - timedelta(minutes=2)), rules, order, EURUSD, now=NOW)
    assert any(hit.code == "MIN_TIME_BETWEEN_TRADES" and hit.decision == Decision.BLOCK for hit in recent.hits)


def test_a_disabled_rule_is_not_enforced():
    rules = EffectiveRules(disabled=frozenset({"MIN_MINUTES_BETWEEN_TRADES", "MAX_LOT", "MAX_DAILY_LOSS_PCT", "MAX_TOTAL_DRAWDOWN_PCT"}))
    order = ProposedOrder("EURUSD", "buy", Decimal("1"), Decimal("1.10000"), Decimal("1.09800"))
    recent = evaluate_proposed(
        _state(last_entry_at=NOW - timedelta(seconds=30), equity=Decimal("8000"), peak_equity=Decimal("10000")),
        rules,
        order,
        EURUSD,
        now=NOW,
    )
    codes = {hit.code for hit in recent.hits}
    assert "MIN_TIME_BETWEEN_TRADES" not in codes
    assert "MAX_LOT" not in codes
    assert "MAX_DAILY_LOSS" not in codes
    assert "MAX_DRAWDOWN" not in codes


def test_a_missing_symbol_spec_does_not_block_the_order():
    blank = SymbolSpec("Volatility 75 (1s) Index", Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "USD")
    order = ProposedOrder("Volatility 75 (1s) Index", "sell", Decimal("0.01"), Decimal("5450"), Decimal("5535"))
    result = evaluate_proposed(_state(), EffectiveRules(disabled=frozenset({"RISK_PER_TRADE_PCT", "MAX_LOT"})), order, blank, now=NOW)
    assert not any(hit.code == "INCOMPLETE_SPEC" and hit.decision == Decision.BLOCK for hit in result.hits)
    assert result.decision != Decision.BLOCK


def test_engine_failure_blocks():
    result = evaluate_fail_closed(_state(), None)  # type: ignore[arg-type]
    assert result.decision == Decision.BLOCK
    assert result.hits[0].code == "ENGINE_FAILURE"


def test_overtrading_states_are_measured():
    quiet = [TradeSample("EURUSD", Decimal("0.1"), NOW - timedelta(hours=5), NOW - timedelta(hours=4), Decimal("10"))]
    assert assess_overtrading(quiet, NOW).state == OvertradingState.NORMAL
    burst = []
    for index in range(12):
        opened = NOW - timedelta(minutes=50 - index)
        burst.append(TradeSample("EURUSD", Decimal("0.1") * (index + 1), opened, opened + timedelta(seconds=20), Decimal("-5")))
    assessment = assess_overtrading(burst, NOW)
    assert assessment.metrics.trades_per_day == 12
    assert assessment.metrics.loss_streak >= 8
    assert assessment.state in {OvertradingState.HIGH, OvertradingState.CRITICAL}


def test_performance_profit_factor_and_expectancy():
    stats = performance_stats([Decimal("100"), Decimal("50"), Decimal("-40"), Decimal("-10")])
    assert stats.win_rate == Decimal("0.50000000")
    assert stats.profit_factor == Decimal("3.00000000")
    assert stats.expectancy == Decimal("25.00000000")
    assert stats.profit_factor is not None


def test_stale_quote_detection():
    assert quote_is_stale(None, NOW, 30) is True
    assert quote_is_stale(NOW - timedelta(seconds=10), NOW, 30) is False
    assert quote_is_stale(NOW - timedelta(seconds=31), NOW, 30) is True


def test_zero_gross_loss_profit_factor_is_null():
    stats = performance_stats([Decimal("10"), Decimal("5")])
    assert stats.profit_factor is None

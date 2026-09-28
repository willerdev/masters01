from decimal import Decimal

from app.services.trade_watch import format_update, pending_codes


class _Position:
    side = "buy"
    symbol = "Volatility 90 (1s) Index"
    volume = Decimal("0.02")
    ticket = "900"
    current_price = Decimal("110")
    entry_price = Decimal("100")
    stop_loss = Decimal("90")
    profit = Decimal("12.5")
    comment = "Signals"
    strategy = ""


def test_a_new_trade_at_entry_is_quiet():
    assert pending_codes("buy", Decimal("100"), Decimal("100"), Decimal("90"), Decimal("0"), set()) == []


def test_profit_then_one_to_one_asks_for_partials_and_breakeven():
    first = pending_codes("buy", Decimal("100"), Decimal("102"), Decimal("90"), Decimal("2"), set())
    assert "profit" in first
    assert "rr1" not in first
    seen = set(first)
    reached = pending_codes("buy", Decimal("100"), Decimal("110"), Decimal("90"), Decimal("12"), seen)
    assert "rr1" in reached
    assert "profit" not in reached
    text = format_update(_Position(), reached)
    assert "1:1" in text
    assert "partials" in text
    assert "breakeven" in text
    assert "Signals" in text


def test_a_jump_to_two_reward_includes_the_one_to_one_reminder():
    codes = pending_codes("sell", Decimal("100"), Decimal("80"), Decimal("110"), Decimal("20"), set())
    assert codes == ["profit", "moved", "rr1", "rr2"]
    text = format_update(_Position(), [code for code in codes if code != "moved"])
    assert "1:1" in text
    assert "2:1" in text
    assert "The trade is in profit." not in text


def test_price_back_at_entry_is_announced_once_after_it_moved():
    moved = pending_codes("buy", Decimal("100"), Decimal("103"), Decimal("90"), Decimal("3"), set())
    assert "moved" in moved
    back = pending_codes("buy", Decimal("100"), Decimal("100.2"), Decimal("90"), Decimal("0.1"), set(moved))
    assert back == ["entry"]
    again = pending_codes("buy", Decimal("100"), Decimal("100"), Decimal("90"), Decimal("0"), set(moved) | set(back))
    assert again == []


def test_reward_levels_three_and_four_are_separate():
    seen = {"profit", "moved", "rr1", "rr2"}
    third = pending_codes("buy", Decimal("100"), Decimal("130"), Decimal("90"), Decimal("30"), seen)
    assert third == ["rr3"]
    fourth = pending_codes("buy", Decimal("100"), Decimal("140"), Decimal("90"), Decimal("40"), seen | {"rr3"})
    assert fourth == ["rr4"]


def test_a_trade_without_a_stop_can_still_report_profit():
    codes = pending_codes("buy", Decimal("100"), Decimal("101"), None, Decimal("1"), set())
    assert codes == ["profit", "moved"]
    assert pending_codes("buy", Decimal("100"), Decimal("102"), None, Decimal("2"), set(codes)) == []

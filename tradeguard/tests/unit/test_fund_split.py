from decimal import Decimal

from app.services.fund_service import split_volume


def test_volume_split_uses_equity_and_keeps_the_total():
    parts = split_volume(Decimal("1.00"), [Decimal("7500"), Decimal("2500")])
    assert parts == [Decimal("0.75"), Decimal("0.25")]
    assert sum(parts, Decimal("0")) == Decimal("1.00")


def test_equal_split_when_equity_is_zero():
    parts = split_volume(Decimal("0.03"), [Decimal("0"), Decimal("0"), Decimal("0")])
    assert sum(parts, Decimal("0")) == Decimal("0.03")

from decimal import Decimal

import pytest
from tradeguard_risk.types import SymbolSpec

from app.services.order_service import OrderError, _fit_volume, resolve_broker_symbol

KNOWN = [
    "Volatility 75 Index",
    "Volatility 75 (1s) Index",
    "Volatility 15 (1s) Index",
    "Volatility 100 (1s) Index",
    "XAUUSD",
]


def test_vix_75_is_the_volatility_75_index():
    assert resolve_broker_symbol("VIX 75", KNOWN) == "Volatility 75 Index"
    assert resolve_broker_symbol("vol 75", KNOWN) == "Volatility 75 Index"
    assert resolve_broker_symbol("volatility 75", KNOWN) == "Volatility 75 Index"


def test_vix_75_1s_keeps_the_one_second_symbol():
    assert resolve_broker_symbol("vix 75 1s", KNOWN) == "Volatility 75 (1s) Index"
    assert resolve_broker_symbol("VIX 15 1s", KNOWN) == "Volatility 15 (1s) Index"


def test_a_bare_vix_asks_which_volatility_index():
    with pytest.raises(OrderError) as caught:
        resolve_broker_symbol("VIX", KNOWN)
    assert "Volatility 75 Index" in caught.value.detail
    assert "ticker" not in caught.value.detail.lower() or "VIX" in caught.value.detail


def test_gold_and_exact_names_stay_unchanged():
    assert resolve_broker_symbol("XAUUSD", KNOWN) == "XAUUSD"
    assert resolve_broker_symbol("volatility 100 (1s) index", KNOWN) == "Volatility 100 (1s) Index"


def test_an_unlisted_vix_number_uses_the_broker_name():
    assert resolve_broker_symbol("VIX 50", ["XAUUSD"]) == "Volatility 50 Index"


def test_a_lot_below_the_symbol_minimum_is_raised():
    spec = SymbolSpec("Volatility 75 (1s) Index", Decimal("0.01"), Decimal("0.01"), Decimal("1"), Decimal("0.05"), Decimal("80"), Decimal("0.001"), "USD")
    assert _fit_volume(Decimal("0.01"), spec) == Decimal("0.05")

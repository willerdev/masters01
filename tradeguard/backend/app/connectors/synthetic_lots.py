"""Minimum lot sizes published by Deriv for synthetic indices, and the stop plan for a signal that omits one."""

from __future__ import annotations

import re
from decimal import Decimal

from tradeguard_risk.types import SymbolSpec

# Min size column on https://deriv.com/markets/derived-indices/synthetic-indices
_MINIMUMS: dict[str, str] = {
    "aud basket": "0.01",
    "boom 1000 index": "0.2",
    "boom 100 index": "0.1",
    "boom 150 index": "0.5",
    "boom 200 index": "0.1",
    "boom 300 index": "0.5",
    "boom 500 index": "0.2",
    "boom 50 index": "0.1",
    "boom 600 index": "0.2",
    "boom 900 index": "0.2",
    "boom 99 index": "0.1",
    "btceth arbitrage index long btc": "0.1",
    "btceth arbitrage index long eth": "0.1",
    "crash 1000 index": "0.2",
    "crash 100 index": "0.1",
    "crash 150 index": "0.5",
    "crash 200 index": "0.1",
    "crash 300 index": "0.5",
    "crash 500 index": "0.2",
    "crash 50 index": "0.1",
    "crash 600 index": "0.2",
    "crash 900 index": "0.2",
    "crash 99 index": "0.1",
    "crash boom flip 1000 index": "0.1",
    "crash boom flip 150 index": "0.1",
    "crash boom flip 300 index": "0.1",
    "crash boom flip 500 index": "0.1",
    "dex 1500 down index": "0.01",
    "dex 1500 up index": "0.1",
    "dex 600 down index": "0.1",
    "dex 600 up index": "0.1",
    "dex 900 down index": "0.01",
    "dex 900 up index": "0.1",
    "drift switch index 10": "0.1",
    "drift switch index 20": "0.1",
    "drift switch index 30": "0.1",
    "eur basket": "0.01",
    "exponential growth index 1": "0.01",
    "exponential growth index 2": "0.01",
    "gbp basket": "0.01",
    "gold basket": "0.01",
    "gold rsi pullback index": "0.1",
    "gold rsi rebound index": "0.1",
    "gold rsi trend down index": "0.1",
    "gold rsi trend up index": "0.1",
    "high frequency vol 100 index": "0.05",
    "high frequency vol 10 index": "0.1",
    "high frequency vol 25 index": "0.1",
    "high frequency vol 50 index": "0.05",
    "high frequency vol 75 index": "0.05",
    "jump 100 index": "0.1",
    "jump 10 index": "0.01",
    "jump 25 index": "0.01",
    "jump 50 index": "0.01",
    "jump 75 index": "0.01",
    "multi step 2 index": "0.1",
    "multi step 3 index": "0.1",
    "multi step 4 index": "0.1",
    "range break 100 index": "0.01",
    "range break 200 index": "0.01",
    "silver rsi pullback index": "0.1",
    "silver rsi rebound index": "0.1",
    "silver rsi trend down index": "0.1",
    "silver rsi trend up index": "0.1",
    "skew step index 4 down": "0.1",
    "skew step index 5 down": "0.1",
    "skew step index 4 up": "0.1",
    "skew step index 5 up": "0.1",
    "spot up - volatility down index": "0.1",
    "spot up - volatility up index": "0.1",
    "step index": "0.1",
    "step index 200": "0.1",
    "step index 300": "0.1",
    "step index 400": "0.1",
    "step index 500": "0.1",
    "trek down index": "0.1",
    "trek up index": "0.1",
    "usd basket": "0.01",
    "volatility 100 (1s) index": "1",
    "volatility 100 index": "1",
    "volatility 10 (1s) index": "0.5",
    "volatility 10 index": "0.5",
    "volatility 150 (1s) index": "1",
    "volatility 15 (1s) index": "0.2",
    "volatility 15 index": "0.1",
    "volatility 250 (1s) index": "10",
    "volatility 25 (1s) index": "0.005",
    "volatility 25 index": "0.5",
    "volatility 30 (1s) index": "0.2",
    "volatility 30 index": "0.05",
    "volatility 50 (1s) index": "0.005",
    "volatility 50 index": "4",
    "volatility 5 (1s) index": "0.05",
    "volatility 5 index": "0.05",
    "volatility 75 (1s) index": "0.05",
    "volatility 75 index": "0.01",
    "volatility 90 (1s) index": "0.1",
    "volatility 90 index": "0.05",
    "vol over boom 400": "0.1",
    "vol over boom 550": "0.1",
    "vol over boom 750": "0.1",
    "vol over crash 400": "0.1",
    "vol over crash 550": "0.1",
    "vol over crash 750": "0.1",
    "volswitch high vol index": "0.1",
    "volswitch low vol index": "0.1",
    "volswitch medium vol index": "0.1",
}


def minimum_lot(symbol: str) -> Decimal | None:
    key = _key(symbol)
    if key in _MINIMUMS:
        return Decimal(_MINIMUMS[key])
    match = re.search(r"(?:volatility|vol|vix)\s*(\d+)(.*)$", key)
    if not match:
        return None
    speed = " (1s)" if re.search(r"1\s*s", match.group(2)) else ""
    return _decimal_or_none(_MINIMUMS.get(f"volatility {match.group(1)}{speed} index"))


def pip_size(symbol: str, spec: SymbolSpec | None) -> Decimal:
    """One pip. Synthetic indices use 0.01 unless the broker point is larger. Forex uses the standard pip."""
    if minimum_lot(symbol) is not None:
        point = Decimal("0.01")
        if spec is not None and spec.tick_size > point:
            return spec.tick_size
        return point
    if spec is not None and spec.tick_size > 0:
        if spec.digits in {3, 5}:
            return spec.tick_size * 10
        return spec.tick_size
    from app.connectors.symbol_catalog import catalog_spec

    catalog = catalog_spec(symbol)
    if catalog is not None and catalog.tick_size > 0:
        if catalog.digits in {3, 5}:
            return catalog.tick_size * 10
        return catalog.tick_size
    return Decimal("0.0001")


def plan_protection(
    side: str,
    entry: Decimal,
    stop: Decimal | None,
    take: Decimal | None,
    pip: Decimal,
    pips: int = 100,
) -> tuple[Decimal | None, Decimal | None, bool, bool]:
    """Fill a missing stop at `pips` and a missing target at 2R. Returns stop, target, stop_was_calculated, target_was_calculated."""
    calculated_stop = stop is None
    calculated_target = take is None
    if stop is None:
        distance = pip * Decimal(pips)
        stop = entry - distance if side == "buy" else entry + distance
        if stop <= 0:
            stop = None
            calculated_stop = False
    if take is None and stop is not None:
        risk = abs(entry - stop)
        take = entry + (risk * 2) if side == "buy" else entry - (risk * 2)
        if take <= 0:
            take = None
            calculated_target = False
    return stop, take, calculated_stop, calculated_target


def _key(symbol: str) -> str:
    return " ".join(str(symbol or "").strip().lower().split())


def _decimal_or_none(value: str | None) -> Decimal | None:
    if not value:
        return None
    return Decimal(value)

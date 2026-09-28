from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR


def D(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def floor_to_step(volume: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("volume step must be positive")
    steps = (volume / step).to_integral_value(rounding=ROUND_FLOOR)
    return steps * step


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))

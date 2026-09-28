from __future__ import annotations

from decimal import Decimal

from tradeguard_risk.money import D, quantize_money
from tradeguard_risk.sizing import position_risk, suggest_volume
from tradeguard_risk.types import ProposedOrder, SymbolSpec


def _reward(entry: Decimal, take_profit: Decimal | None, stop: Decimal, spec: SymbolSpec, volume: Decimal) -> Decimal | None:
    if take_profit is None or spec.tick_size <= 0:
        return None
    ticks = abs(D(entry) - D(take_profit)) / D(spec.tick_size)
    return quantize_money(ticks * D(spec.tick_value) * D(volume))


def simulate_trade(
    *,
    balance: Decimal,
    risk_percent: Decimal,
    stop_loss: Decimal,
    symbol: str,
    entry_price: Decimal,
    lot_size: Decimal,
    spec: SymbolSpec,
    take_profit: Decimal | None = None,
    side: str = "buy",
    leverage: Decimal = Decimal("100"),
    loss_count: int = 5,
    daily_loss_percent: Decimal = Decimal("3"),
    risk_to_percent: Decimal = Decimal("2"),
) -> dict:
    equity = D(balance)
    order = ProposedOrder(symbol, side, D(lot_size), D(entry_price), D(stop_loss), None if take_profit is None else D(take_profit))
    sized = position_risk(order, spec, equity)
    suggested = suggest_volume(equity, D(risk_percent), D(entry_price), D(stop_loss), spec)
    notional = quantize_money(D(lot_size) * D(spec.contract_size) * D(entry_price) / (Decimal("100000") if spec.calc_mode == "forex" else Decimal("1")))
    if spec.calc_mode == "forex":
        notional = quantize_money(D(lot_size) * D(spec.contract_size))
    margin = quantize_money(notional / D(leverage)) if D(leverage) > 0 else Decimal("0")
    reward = _reward(D(entry_price), None if take_profit is None else D(take_profit), D(stop_loss), spec, D(lot_size))
    risk_amount = sized.risk_amount
    ratio = None
    if reward is not None and risk_amount is not None and risk_amount > 0:
        ratio = quantize_money(reward / risk_amount)
    streak_equity = equity
    for _ in range(max(loss_count, 0)):
        streak_equity = quantize_money(streak_equity * (Decimal("1") - D(risk_percent) / Decimal("100")))
    daily_loss = quantize_money(equity * D(daily_loss_percent) / Decimal("100"))
    budget_from = quantize_money(equity * D(risk_percent) / Decimal("100"))
    budget_to = quantize_money(equity * D(risk_to_percent) / Decimal("100"))
    return {
        "symbol": symbol,
        "potential_loss": None if risk_amount is None else f"{risk_amount:.2f}",
        "risk_percentage": None if sized.risk_percent is None else f"{sized.risk_percent:.2f}",
        "position_size": f"{D(lot_size)}",
        "suggested_volume": None if suggested.suggested_volume is None else f"{suggested.suggested_volume}",
        "margin_requirement": f"{margin:.2f}",
        "exposure": f"{notional:.2f}",
        "risk_reward": None if ratio is None else f"{ratio:.2f}",
        "incomplete": sized.incomplete,
        "reason": sized.reason,
        "loss_streak": {
            "trades": loss_count,
            "risk_percent": f"{D(risk_percent):.2f}",
            "equity_after": f"{streak_equity:.2f}",
            "capital_lost": f"{(equity - streak_equity):.2f}",
        },
        "daily_loss": {
            "percent": f"{D(daily_loss_percent):.2f}",
            "loss_amount": f"{daily_loss:.2f}",
            "equity_after": f"{(equity - daily_loss):.2f}",
        },
        "risk_change": {
            "from_percent": f"{D(risk_percent):.2f}",
            "to_percent": f"{D(risk_to_percent):.2f}",
            "loss_budget_from": f"{budget_from:.2f}",
            "loss_budget_to": f"{budget_to:.2f}",
        },
    }

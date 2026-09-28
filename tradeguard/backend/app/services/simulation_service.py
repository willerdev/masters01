from __future__ import annotations

from decimal import Decimal

from app.connectors.symbol_catalog import catalog_spec
from tradeguard_risk.simulation import simulate_trade
from tradeguard_risk.types import SymbolSpec


def run_simulation(payload: dict) -> dict:
    symbol = str(payload["symbol"]).upper()
    spec = catalog_spec(symbol)
    if spec is None:
        spec = SymbolSpec(symbol, Decimal("0"), Decimal("0"), Decimal("1"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "USD")
    return simulate_trade(
        balance=Decimal(payload["balance"]),
        risk_percent=Decimal(payload["risk_percent"]),
        stop_loss=Decimal(payload["stop_loss"]),
        symbol=symbol,
        entry_price=Decimal(payload["entry_price"]),
        lot_size=Decimal(payload["lot_size"]),
        spec=spec,
        take_profit=None if payload.get("take_profit") is None else Decimal(payload["take_profit"]),
        side=str(payload.get("side") or "buy"),
        leverage=Decimal(payload.get("leverage") or "100"),
        loss_count=int(payload.get("loss_count") or 5),
        daily_loss_percent=Decimal(payload.get("daily_loss_percent") or "3"),
        risk_to_percent=Decimal(payload.get("risk_to_percent") or "2"),
    )

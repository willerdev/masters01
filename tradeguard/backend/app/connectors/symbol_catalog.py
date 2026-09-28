from __future__ import annotations

from decimal import Decimal

from tradeguard_risk.types import SymbolSpec

# Catalog values are broker-typical estimates. Live specs from the terminal replace them.
_CATALOG: dict[str, SymbolSpec] = {
    "EURUSD": SymbolSpec("EURUSD", Decimal("0.00001"), Decimal("1"), Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "USD", 5, "forex"),
    "GBPUSD": SymbolSpec("GBPUSD", Decimal("0.00001"), Decimal("1"), Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "USD", 5, "forex"),
    "USDJPY": SymbolSpec("USDJPY", Decimal("0.001"), Decimal("100"), Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"), "JPY", 3, "forex"),
    "XAUUSD": SymbolSpec("XAUUSD", Decimal("0.01"), Decimal("1"), Decimal("100"), Decimal("0.01"), Decimal("50"), Decimal("0.01"), "USD", 2, "metal", "cfd"),
    "XAGUSD": SymbolSpec("XAGUSD", Decimal("0.001"), Decimal("0.5"), Decimal("5000"), Decimal("0.01"), Decimal("50"), Decimal("0.01"), "USD", 3, "metal", "cfd"),
    "US30": SymbolSpec("US30", Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.1"), Decimal("100"), Decimal("0.1"), "USD", 1, "index", "cfd_index"),
    "NAS100": SymbolSpec("NAS100", Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.1"), Decimal("100"), Decimal("0.1"), "USD", 1, "index", "cfd_index"),
    "GER40": SymbolSpec("GER40", Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.1"), Decimal("100"), Decimal("0.1"), "EUR", 1, "index", "cfd_index"),
}


def catalog_spec(symbol: str) -> SymbolSpec | None:
    from app.connectors.normalize import canonical_symbol

    return _CATALOG.get(canonical_symbol(symbol))

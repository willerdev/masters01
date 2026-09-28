from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class NormalizedPosition:
    account_id: str | None
    ticket: str
    symbol: str
    side: str
    volume: Decimal
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    profit: Decimal
    swap: Decimal
    commission: Decimal
    open_time: datetime | None
    magic_number: int | None
    comment: str


@dataclass
class NormalizedQuote:
    symbol: str
    bid: Decimal
    ask: Decimal
    spread: Decimal
    tick_size: Decimal | None
    timestamp: datetime
    source: str


@dataclass
class NormalizedAccount:
    balance: Decimal
    equity: Decimal
    margin: Decimal
    free_margin: Decimal
    margin_level: Decimal | None
    currency: str = "USD"


@dataclass
class ConnectorCapabilities:
    can_read: bool
    can_close: bool
    can_block: bool
    platform: str


@dataclass
class ConnectionTest:
    ok: bool
    status: str
    error_code: str = ""
    detail: str = ""


@dataclass
class CloseResult:
    accepted: bool
    mode: str
    closed_tickets: list[str] = field(default_factory=list)
    error_code: str = ""

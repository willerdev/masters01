from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.connectors.normalize import NormalizeError, normalize_position, normalize_quote
from app.core.resilience import CircuitBreaker, CircuitOpen
from app.services.ingest_service import sign_webhook


def test_normalizes_mt5_field_aliases():
    position = normalize_position(
        {
            "ticket": 55,
            "Symbol": "eurusd.pro",
            "type": 0,
            "lots": "0.10",
            "price_open": "1.08500",
            "price_current": "1.08600",
            "sl": "1.08000",
            "tp": "1.09000",
            "profit": "10",
            "magic": 42,
            "comment": "breakout",
            "openTime": "2026-09-26T10:00:00Z",
        },
        account_id="acc",
    )
    assert position.ticket == "55"
    assert position.symbol == "eurusd.pro"
    assert position.side == "buy"
    assert position.volume == Decimal("0.10")
    assert position.stop_loss == Decimal("1.08000")
    assert position.magic_number == 42
    assert position.open_time == datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)


def test_sell_side_and_missing_symbol():
    sell = normalize_position({"ticket": "9", "symbol": "XAUUSD", "direction": "SHORT", "volume": "0.2", "entryPrice": "2300", "currentPrice": "2290"})
    metaapi = normalize_position(
        {
            "id": "60402126353",
            "symbol": "Volatility 15 (1s) Index",
            "type": "POSITION_TYPE_BUY",
            "volume": 0.2,
            "openPrice": 1.25,
            "currentPrice": 1.26,
            "profit": 2,
        }
    )
    assert metaapi.ticket == "60402126353"
    assert metaapi.side == "buy"
    assert metaapi.entry_price == Decimal("1.25")
    assert sell.side == "sell"
    with pytest.raises(NormalizeError):
        normalize_position({"ticket": "1", "volume": "1"})


def test_quote_spread_and_signature():
    quote = normalize_quote({"symbol": "EURUSD", "bid": "1.10000", "ask": "1.10002", "timestamp": "2026-09-26T12:00:00Z"}, source="mt5")
    assert quote.spread == Decimal("0.00002")
    body = b'{"event_id":"1"}'
    signature = sign_webhook("secret", "100", "nonce", body)
    assert signature == sign_webhook("secret", "100", "nonce", body)
    assert signature != sign_webhook("secret", "101", "nonce", body)


def test_circuit_breaker_opens_and_stops_calling():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("down")

    breaker = CircuitBreaker(fail_max=3, reset_seconds=60)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(boom)
    with pytest.raises(CircuitOpen):
        breaker.call(boom)
    assert calls["n"] == 3

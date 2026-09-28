# Webhooks

`POST /api/v1/webhooks/mt5/{token}`

Headers:

- `X-Tradeguard-Key` — API key returned once at account creation
- `X-Tradeguard-Timestamp` — unix seconds
- `X-Tradeguard-Nonce` — unique within the skew window
- `X-Tradeguard-Signature` — hex HMAC-SHA256 of `timestamp.nonce.raw_body` using the signing secret

The timestamp must fall inside 300 seconds of server time. A reused nonce on an authenticated request is rejected. `event_id` is unique per endpoint.

Body:

```json
{
  "event_id": "8f1c",
  "event_type": "ORDER_OPENED",
  "occurred_at": "2026-09-26T12:00:00Z",
  "account_number": "100200",
  "data": {
    "ticket": "501",
    "symbol": "EURUSD",
    "side": "buy",
    "volume": "0.10",
    "entry_price": "1.10000",
    "current_price": "1.10020",
    "stop_loss": "1.09800",
    "take_profit": "1.10400",
    "profit": "2",
    "magic_number": 7,
    "comment": "open-drive"
  }
}
```

Supported `event_type` values: `ORDER_OPENED`, `ORDER_CLOSED`, `ORDER_MODIFIED`, `POSITION_UPDATED`, `ACCOUNT_UPDATE`, `HEARTBEAT`.

Optional `data.symbol_spec` may include `tick_size`, `tick_value`, `contract_size`, `volume_step`, `volume_min`, `volume_max`, `profit_currency`, `digits`, and `calc_mode`. Those values override the catalog for that broker symbol.

The response includes the risk `decision`: `ALLOW`, `WARNING`, `BLOCK`, or `EMERGENCY_STOP`. Every decision is stored. A duplicate `event_id` returns HTTP 200 and does not evaluate again.

Sign in Python:

```python
import hashlib, hmac
msg = timestamp.encode() + b"." + nonce.encode() + b"." + body
signature = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
```

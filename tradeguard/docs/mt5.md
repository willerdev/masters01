# MT5 connection

Three adapters share one normalized position shape: account id, ticket, symbol, side, volume, prices, stop, target, profit, swap, commission, open time, magic number, and comment.

## Webhook

Create an account with connection method `webhook`. The response includes a path, API key, and signing secret once. Point an EA or bridge at `POST /api/v1/webhooks/mt5/{token}`. See `webhooks.md`.

Connect marks the endpoint enabled. Disconnect disables it. Test connection reports whether a heartbeat arrived inside 90 seconds.

## MetaAPI

The desk asks for the token and account id. TradeGuard reads the account from `GET /users/current/accounts/{id}` on the provisioning API, takes `region` from that record, and continues only when `state` is `DEPLOYED` and `connectionStatus` is `CONNECTED`. It then reads account information from `https://mt-client-api-v1.{region}.agiliumtrade.ai`. Name, login, server, broker, currency, and leverage are stored from that response. The region is saved with the encrypted token. The token is not returned by the connection check.

Close-all issues DELETE requests for each open position when the circuit breaker is closed. Failures stay on that provider and do not stop other accounts.

## Local terminal

The official `MetaTrader5` Python package imports only on Windows beside a running terminal. The connection check logs in with the login, password, and server, then reads the account name, number, broker, currency, and leverage from the terminal. On another operating system the check returns `windows_terminal_required` and the account is not saved. Close requests are queued in `broker_commands` for the agent to ack.

## Prices

Quotes are normalized to bid, ask, spread, tick, timestamp, and source. A quote older than `STALE_QUOTE_SECONDS` (default 30) is stale. Stale input is stored on the risk decision and does not by itself hide a hard breach.

Symbol specs sent on an event are stored as exact. Known symbols without a spec use a labeled catalog estimate. Unknown symbols without a spec cannot be sized, and a proposed order is blocked as incomplete rather than assumed to be EURUSD.

# API

Interactive schema: `http://localhost:8000/docs`.

All control-plane routes live under `/api/v1`. Browser sessions send an httpOnly access cookie plus `Authorization: Bearer` and the header `X-Tradeguard-Request: 1` on cookie-authenticated mutations.

## Auth

- `POST /auth/register` creates an organization and a SUPER_ADMIN.
- `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`.
- `POST /auth/mfa` finishes login when Google Authenticator is enabled. Login then returns `mfa_required` and a five-minute `mfa_token` instead of a session.
- `POST /auth/forgot-password` stores a hashed reset token for 30 minutes and emails it when SMTP is set.
- `POST /auth/reset-password` consumes the token and revokes sessions.
- `GET/POST /users` requires `users.manage`. Only SUPER_ADMIN can grant SUPER_ADMIN.

Roles: SUPER_ADMIN, ADMIN, RISK_MANAGER, TRADER, VIEWER.

## Accounts and risk

- `POST /connections/probe` checks a MetaAPI token and account id, or a local MT5 login, before an account is saved. The response includes the discovered region and account identity, and never the token or password.
- `GET/POST /accounts`, `GET/PATCH /accounts/{id}`. MetaAPI and local MT5 accounts are created only after the same live check succeeds.
- `POST /accounts/{id}/connect|disconnect|test-connection|monitoring`
- `POST /accounts/{id}/webhook/rotate` returns the new secret once
- `GET/PUT /accounts/{id}/risk-rules`
- `GET /accounts/{id}/positions`, `GET /accounts/{id}/trades`, `GET /trades`
- `POST /accounts/{id}/emergency` with `confirm` set to the exact action phrase
- `GET /accounts/{id}/commands` pending close or block commands for an EA

## Desk

- `GET /dashboard/summary`
- `GET /dashboard/charts`
- `GET /alerts`, `GET /notifications`, `POST /notifications/{id}/read`
- `PUT /alert-channels`
- `GET /audit-logs` read-only
- `PUT /ai/config` providers: `openai`, `gemini`, `anthropic`, `deepseek`, `local`. `POST /accounts/{id}/ai/analyze`
- `GET /setup/status` and `POST /setup/complete` collect country, language, phone country code, phone number, admin email, a Google Authenticator code, and one MetaAPI or same-device MetaTrader 5 account.
- `POST/GET /api-keys`, `DELETE /api-keys/{id}`

## Crypto payments

- `GET/PUT /payments/provider` stores one provider per organization: `nowpayments` or `cryptomus`. NOWPayments asks for the API key, API URL, payout email, payout password, and IPN secret. Cryptomus asks for the merchant id and payment API key. Those secrets are encrypted. The response never returns them. Saving checks the API key and, for NOWPayments, the payout login. The provider is kept only when that check succeeds.
- `POST /payments` asks the connected provider to create a payment. The local status stays unpaid until a signed notification arrives. `ledger_posted` is false: a paid crypto invoice does not change trading equity or investor units.
- `GET /payments` lists payment requests for the caller's organization.
- `POST /payments/ipn/nowpayments/{organization_id}` checks the `x-nowpayments-sig` HMAC-SHA512.
- `POST /payments/ipn/cryptomus/{organization_id}` checks the Cryptomus `sign`. A wrong signature does not change the payment.

## Platform

- `POST /simulate` sizes a hypothetical order and the loss-streak, daily-loss, and risk-change scenarios.
- `GET /portfolio` returns combined capital, equity, exposure, open risk, drawdown, and shared-currency overlap.
- `GET /accounts/{id}/health` returns HEALTHY, WARNING, HIGH_RISK, or CRITICAL with measured reasons.
- `GET /accounts/{id}/behavior` returns observed trade-flow features.
- `POST /accounts/{id}/copilot` answers from account data.
- `GET /reports?period=daily|weekly|monthly&kind=risk|performance|violations|behavior&format=json|csv|pdf`
- `GET /closed-trades`, `GET /risk-decisions`
- `GET/POST /copy-links`, `DELETE /copy-links/{id}`, `GET /copy-decisions`
- `GET /ready` checks PostgreSQL and Redis.
- `GET /metrics` requires `audit.read` or `X-Metrics-Token` when `METRICS_TOKEN` is set.

`GET /health` and `GET /ready` are also mounted at the process root.

## Webhook

`POST /webhooks/mt5/{token}` is documented in `webhooks.md`. A new event returns 202. A repeated `event_id` returns 200 with `duplicate: true`.

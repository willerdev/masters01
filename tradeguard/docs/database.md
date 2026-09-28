# Database

PostgreSQL 16 is the ledger. Redis is the Celery broker only.

Apply the schema with Alembic from `database/`:

```bash
DATABASE_URL=postgresql+psycopg://tradeguard:tradeguard@localhost:5432/tradeguard alembic upgrade head
```

The initial revision creates every table from the SQLAlchemy metadata and, on PostgreSQL, installs a trigger that rejects UPDATE and DELETE on `audit_logs`. The application also refuses those operations in the ORM.

Money and prices are `NUMERIC`. Primary keys are UUIDs.

Core groups:

- Identity: `organizations`, `users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `sessions`, `password_reset_tokens`, `user_mfa_factors`
- Accounts: `accounts`, `account_grants`, `account_credentials`, `account_connections`, `account_state`, `account_snapshots`
- Trading: `symbol_specs`, `positions`, `trades`, `orders`, `market_quotes`
- Risk: `risk_profiles`, `risk_rules`, `risk_decisions`, `risk_violations`, `overtrading_assessments`, `emergency_actions`, `broker_commands`
- Delivery: `alerts`, `notifications`, `notification_deliveries`, `alert_channel_configs`, `webhook_endpoints`, `webhook_inbox`, `webhook_nonces`
- Analytics: `equity_snapshots`, `drawdown_snapshots`, `daily_statistics`
- Other: `api_keys`, `ai_provider_configs`, `ai_requests`, `audit_logs`, `system_events`

`account_credentials` stores AES-GCM nonce and ciphertext. List and detail responses never select that table.

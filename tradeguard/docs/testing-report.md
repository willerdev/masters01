# Testing report

Command:

```bash
cd tradeguard
.venv/bin/pytest
```

The suite covers risk calculations, position sizing, daily loss, drawdown, trade limits, overtrading, webhook duplicates and signatures, authentication, viewer permissions, MT5 normalization, circuit-breaker failure, session revocation, login rate limiting, the simulator, portfolio totals, account-health reasons, behavior measurements, PDF output, copilot structure with AI disabled, readiness, and metrics.

A load check builds a 100-account portfolio and measures 1,000 historical trades in process. It does not open 1,000 broker connections.

Webhook duplicates, disconnect handling, and AI failure are covered by the integration tests. Redis is not required for those tests because nonce and decision storage are in PostgreSQL. `/api/v1/ready` reports Redis as down when it is unreachable and still returns 200 when PostgreSQL answers.

# TradeGuard

TradeGuard is a multi-account MetaTrader 5 risk desk. The deterministic risk engine decides ALLOW, WARNING, BLOCK, or EMERGENCY_STOP. AI commentary cannot change those limits.

## Layout

```
tradeguard/
  frontend/       Next.js desk
  backend/        FastAPI control plane
  risk-engine/    Pure Decimal risk math
  workers/        Celery heartbeat sweep
  shared/         Event types and role names
  database/       Alembic migrations
  docker/         Compose and images
  docs/           API, security, MT5, deployment
  tests/          Unit and PostgreSQL integration tests
```

## Local startup

PostgreSQL 16 and Redis must be running.

```bash
cd tradeguard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
export $(grep -v '^#' .env | xargs)
cd database && ../.venv/bin/alembic upgrade head && cd ..
.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

In a second terminal:

```bash
cd tradeguard/workers
PYTHONPATH=../backend:../risk-engine:../shared/python:. ../.venv/bin/celery -A celery_app.celery worker --beat --loglevel=INFO
```

In a third terminal:

```bash
cd tradeguard/frontend
npm install
npm run dev
```

Open http://localhost:3000. With the example env, sign in as `admin@example.com` / `LocalAdmin12!`. That password is for local development only. Change it before any shared deployment.

## Docker

From `tradeguard/`, after copying `.env.example` to `.env`:

```bash
docker compose -f docker/docker-compose.yml up --build
```

## Tests

```bash
cd tradeguard
DATABASE_URL=postgresql+psycopg://tradeguard:tradeguard@localhost:5432/tradeguard_test .venv/bin/pytest
```

Create `tradeguard_test` once if it does not exist.

## Migrations

```bash
cd tradeguard/database
DATABASE_URL=postgresql+psycopg://tradeguard:tradeguard@localhost:5432/tradeguard ../.venv/bin/alembic upgrade head
```

Further operating detail is in `docs/`, including architecture, AI, recovery, and the user manual.

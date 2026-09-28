# Deployment

## Local Docker

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Published ports: API `8000`, desk `3000`. Postgres and Redis are not published.

The backend container runs `alembic upgrade head` before Uvicorn. The worker container runs Celery with beat for the 15-second heartbeat sweep. The API process also sweeps heartbeats, so a single-node install still detects disconnects if the worker is briefly down.

## Production

1. Set `ENVIRONMENT=production`.
2. Replace `JWT_SECRET`, `MASTER_KEY`, and `SEED_ADMIN_PASSWORD`. The process refuses the documented local master key and the local admin password.
3. Set `COOKIE_SECURE=true` and `CORS_ORIGINS` to the desk origin.
4. Terminate TLS in front of the API and the desk. Caddy or another reverse proxy is enough on a Linux VPS.
5. Keep Postgres volumes and take a daily base backup plus WAL archiving. Restore it once before calling the deploy finished.
6. Set `SEED_SAMPLE_DATA=false`.
7. Leave Redis private. It is a broker, not the source of truth. Accepted webhook events are committed in PostgreSQL before the 202 response.

Scale the API and the Celery worker as separate replicas. Do not run more than one beat scheduler.

## Health

`GET /api/v1/health` returns `{"status":"ok"}` when the process is up. It does not claim the database is healthy by itself; a failed migration prevents the process from serving.

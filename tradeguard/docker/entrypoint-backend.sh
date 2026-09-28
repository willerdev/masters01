#!/bin/sh
set -eu
cd /srv/database
alembic upgrade head
cd /srv/backend
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

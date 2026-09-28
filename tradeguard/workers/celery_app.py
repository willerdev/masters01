import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for path in (os.path.join(ROOT, "backend"), os.path.join(ROOT, "risk-engine"), os.path.join(ROOT, "shared", "python")):
    if path not in sys.path:
        sys.path.insert(0, path)

from celery import Celery
from app.core.config import get_settings

settings = get_settings()
celery = Celery("tradeguard", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_default_retry_delay=5)


@celery.task(name="tradeguard.sweep_heartbeats")
def sweep_heartbeats_task() -> int:
    from app.core.database import SessionLocal
    from app.services.ingest_service import sweep_heartbeats

    db = SessionLocal()
    try:
        changed = sweep_heartbeats(db)
        db.commit()
        return changed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery.task(name="tradeguard.dispatch_pending")
def dispatch_pending_task() -> str:
    return "alerts are delivered when they are raised"


celery.conf.beat_schedule = {
    "sweep-heartbeats": {"task": "tradeguard.sweep_heartbeats", "schedule": 15.0},
}

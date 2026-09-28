from __future__ import annotations

import logging
import threading
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.platform import metrics as metrics_endpoint
from app.api.v1.platform import ready as ready_endpoint
from app.api.v1.payments import router as payments_router
from app.api.v1.portal import router as portal_router
from app.api.v1.assets import router as assets_router
from app.api.v1.funds import router as funds_router
from app.api.v1.journal import router as journal_router
from app.api.v1.recovery import router as recovery_router
from app.api.v1.platform import router as platform_router
from app.api.v1.router import router
from app.api.v1.setup_routes import router as setup_router
from app.core.telemetry import RequestTimer, telemetry
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.redaction import configure_logging
from app.services.auth_service import ensure_rbac
from app.services.ingest_service import sweep_heartbeats
from app.services.seed import seed_admin, seed_sample

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title="TradeGuard", version="0.1.0", docs_url="/docs", redoc_url="/redoc")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")
    app.include_router(setup_router, prefix="/api/v1")
    app.include_router(platform_router, prefix="/api/v1")
    app.include_router(payments_router, prefix="/api/v1")
    app.include_router(recovery_router, prefix="/api/v1")
    app.include_router(journal_router, prefix="/api/v1")
    app.include_router(funds_router, prefix="/api/v1")
    app.include_router(assets_router, prefix="/api/v1")
    app.include_router(portal_router, prefix="/api/v1")

    @app.middleware("http")
    async def observe_request(request, call_next):
        timer = RequestTimer()
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        telemetry.observe(request.url.path, response.status_code, timer.elapsed_ms())
        logging.getLogger("tradeguard.http").info(
            "http_request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            timer.elapsed_ms(),
        )
        return response

    @app.get("/health")
    def root_health() -> dict:
        return {"status": "ok", "service": "tradeguard"}

    @app.get("/ready")
    def root_ready(db=Depends(get_db)):
        return ready_endpoint(db)

    @app.get("/metrics")
    def root_metrics(request: Request, db=Depends(get_db)):
        return metrics_endpoint(request, db)

    @app.on_event("startup")
    def startup() -> None:
        if settings.environment == "test":
            return
        db = SessionLocal()
        try:
            ensure_rbac(db)
            seed_admin(db)
            if settings.seed_sample_data:
                seed_sample(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("startup_seed_failed")
        finally:
            db.close()
        if settings.environment != "test":
            threading.Thread(target=_heartbeat_loop, name="heartbeat-sweep", daemon=True).start()
            threading.Thread(target=_live_book_loop, name="live-book", daemon=True).start()
            threading.Thread(target=_telegram_trade_loop, name="telegram-trades", daemon=True).start()
            threading.Thread(target=_telegram_copy_loop, name="telegram-copy", daemon=True).start()

    return app


def _live_book_loop() -> None:
    """Keep open prices in the database so the desk can read them without waiting on the broker."""
    from app.services.live_trades import refresh_live_books

    while True:
        started = time.monotonic()
        db = SessionLocal()
        try:
            refresh_live_books(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("live_book_failed")
        finally:
            db.close()
        time.sleep(max(0.0, 2.0 - (time.monotonic() - started)))


def _telegram_trade_loop() -> None:
    from app.services.alert_service import drain_telegram_trades

    while True:
        db = SessionLocal()
        try:
            drain_telegram_trades(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("telegram_trade_failed")
        finally:
            db.close()
        time.sleep(2)


def _telegram_copy_loop() -> None:
    from app.services.telegram_user import drain_copied_signals

    while True:
        db = SessionLocal()
        try:
            drain_copied_signals(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("telegram_copy_failed")
        finally:
            db.close()
        time.sleep(2)


def _heartbeat_loop() -> None:
    while True:
        time.sleep(15)
        db = SessionLocal()
        try:
            sweep_heartbeats(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("heartbeat_sweep_failed")
        finally:
            db.close()


app = create_app()

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.config import get_settings
from app.core.database import get_db
from app.core.telemetry import telemetry
from app.domain.audit import write_audit
from app.models.entities import Account, AccountState, ClosedTrade, CopyDecision, CopyLink, Position, RiskDecisionRow
from app.services.account_service import visible_account_query
from app.services.behavior_service import account_behavior
from app.services.health_service import account_health
from app.services.portfolio_service import portfolio_for
from app.services.report_service import build_report, report_csv, report_pdf
from app.services.simulation_service import run_simulation
from app.api.v1.router import _account_or_404, _client_ip, _trade_payload

router = APIRouter()


class SimIn(BaseModel):
    balance: Decimal
    risk_percent: Decimal = Decimal("1")
    stop_loss: Decimal
    symbol: str
    entry_price: Decimal
    lot_size: Decimal
    take_profit: Decimal | None = None
    side: str = "buy"
    leverage: Decimal = Decimal("100")
    loss_count: int = 5
    daily_loss_percent: Decimal = Decimal("3")
    risk_to_percent: Decimal = Decimal("2")


class CopyIn(BaseModel):
    master_account_id: UUID
    follower_account_id: UUID
    volume_scale: Decimal = Decimal("1")


@router.post("/simulate")
def simulate(payload: SimIn, principal: Principal = Depends(get_principal)):
    principal.require("accounts.read")
    return run_simulation(payload.model_dump())


@router.get("/portfolio")
def portfolio(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    return portfolio_for(db, principal.user, principal.roles)


@router.get("/accounts/{account_id}/health")
def health(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    return account_health(db, account)


@router.get("/accounts/{account_id}/behavior")
def behavior(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    return account_behavior(db, account)


@router.get("/reports")
def reports(period: str = "daily", kind: str = "risk", format: str = "json", principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    if period not in {"daily", "weekly", "monthly"} or kind not in {"risk", "performance", "violations", "behavior"}:
        raise HTTPException(400, "Unknown report")
    report = build_report(db, principal.user, principal.roles, period=period, kind=kind)
    if format == "csv":
        return Response(report_csv(report), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="tradeguard-{kind}-{period}.csv"'})
    if format == "pdf":
        return Response(report_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="tradeguard-{kind}-{period}.pdf"'})
    return report


@router.get("/closed-trades")
def closed_trades(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    ids = [row.id for row in db.scalars(visible_account_query(db, principal.user, principal.roles)).all()]
    if not ids:
        return []
    rows = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id.in_(ids)).order_by(ClosedTrade.close_time.desc()).limit(500)).all()
    return [_trade_payload(row) for row in rows]


@router.get("/risk-decisions")
def risk_decisions(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    ids = [row.id for row in db.scalars(visible_account_query(db, principal.user, principal.roles)).all()]
    if not ids:
        return []
    rows = db.scalars(select(RiskDecisionRow).where(RiskDecisionRow.account_id.in_(ids)).order_by(RiskDecisionRow.created_at.desc()).limit(200)).all()
    return [
        {
            "id": str(row.id),
            "account_id": str(row.account_id),
            "decision": row.decision,
            "hits": row.hits,
            "risk_amount": None if row.risk_amount is None else str(row.risk_amount),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/copy-links")
def list_copies(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    rows = db.scalars(select(CopyLink).where(CopyLink.organization_id == principal.user.organization_id)).all()
    return [
        {
            "id": str(row.id),
            "master_account_id": str(row.master_account_id),
            "follower_account_id": str(row.follower_account_id),
            "volume_scale": str(row.volume_scale),
            "enabled": row.enabled,
        }
        for row in rows
    ]


@router.post("/copy-links")
def create_copy(payload: CopyIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    master = _account_or_404(db, principal, payload.master_account_id)
    follower = _account_or_404(db, principal, payload.follower_account_id)
    if master.id == follower.id:
        raise HTTPException(400, "A follower must be a different account")
    if payload.volume_scale <= 0:
        raise HTTPException(400, "Volume scale must be positive")
    link = CopyLink(
        organization_id=principal.user.organization_id,
        master_account_id=master.id,
        follower_account_id=follower.id,
        volume_scale=payload.volume_scale,
    )
    db.add(link)
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="copy_link_created",
        entity_type="copy_link",
        entity_id=str(link.id),
        after={"master": str(master.id), "follower": str(follower.id)},
        ip_address=_client_ip(request),
    )
    db.commit()
    return {"id": str(link.id)}


@router.delete("/copy-links/{link_id}")
def delete_copy(link_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    link = db.get(CopyLink, link_id)
    if link is None or link.organization_id != principal.user.organization_id:
        raise HTTPException(404, "Copy link not found")
    link.enabled = False
    db.commit()
    return {"ok": True}


@router.get("/copy-decisions")
def copy_decisions(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    ids = [row.id for row in db.scalars(visible_account_query(db, principal.user, principal.roles)).all()]
    if not ids:
        return []
    rows = db.scalars(select(CopyDecision).where(CopyDecision.follower_account_id.in_(ids)).order_by(CopyDecision.created_at.desc()).limit(100)).all()
    return [
        {
            "id": str(row.id),
            "follower_account_id": str(row.follower_account_id),
            "master_ticket": row.master_ticket,
            "decision": row.decision,
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def readiness(db: Session) -> dict:
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        database = "down"
    redis_status = "down"
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.4)
        redis_status = "ok" if client.ping() else "down"
    except Exception:  # noqa: BLE001
        redis_status = "down"
    accounts = int(db.scalar(select(func.count()).select_from(Account)) or 0) if database == "ok" else 0
    connected = int(db.scalar(select(func.count()).select_from(Account).where(Account.status == "connected")) or 0) if database == "ok" else 0
    return {"database": database, "redis": redis_status, "accounts": accounts, "connected_accounts": connected}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    body = readiness(db)
    status = 200 if body["database"] == "ok" else 503
    return Response(content=__import__("json").dumps(body), status_code=status, media_type="application/json")


@router.get("/metrics")
def metrics(request: Request, db: Session = Depends(get_db)):
    token = get_settings().metrics_token
    header = request.headers.get("x-metrics-token", "")
    if token:
        if header != token:
            raise HTTPException(401, "Metrics token required")
    else:
        principal = get_principal(request, db)
        principal.require("audit.read")
    checks = readiness(db)
    body = telemetry.render()
    body += f'tradeguard_database_up {1 if checks["database"] == "ok" else 0}\n'
    body += f'tradeguard_redis_up {1 if checks["redis"] == "ok" else 0}\n'
    body += f'tradeguard_accounts {checks["accounts"]}\n'
    body += f'tradeguard_connected_accounts {checks["connected_accounts"]}\n'
    return PlainTextResponse(body)

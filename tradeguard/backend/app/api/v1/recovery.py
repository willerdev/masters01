from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.api.v1.router import _client_ip
from app.core.database import get_db
from app.core.rate_limit import auth_limiter
from app.services.recovery_service import RecoveryError, claim_recovery, recovery_status, restore_account, save_recovery

router = APIRouter()


class RecoveryIn(BaseModel):
    email: str
    password: str
    confirm_password: str = ""
    trc20_wallet: str
    next_of_kin_name: str
    second_next_of_kin_name: str


class RecoveryClaimIn(BaseModel):
    email: str
    password: str
    trc20_wallet: str
    next_of_kin_name: str
    second_next_of_kin_name: str


class RecoveryRestoreIn(BaseModel):
    recovery_token: str
    new_password: str = Field(min_length=12, max_length=200)


@router.get("/recovery")
def get_recovery(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    return recovery_status(db, principal.user.organization_id)


@router.put("/recovery")
def put_recovery(payload: RecoveryIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    if auth_limiter.hit(f"recovery-save:{principal.user.id}", limit=10, window_seconds=60):
        raise HTTPException(429, "Too many recovery updates")
    try:
        body = save_recovery(db, principal.user, payload.model_dump(), _client_ip(request))
        db.commit()
    except RecoveryError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return body


@router.post("/recovery/claim")
def post_claim(payload: RecoveryClaimIn, request: Request, db: Session = Depends(get_db)):
    if auth_limiter.hit(f"recovery-claim:{_client_ip(request)}", limit=8, window_seconds=600):
        raise HTTPException(429, "Too many recovery attempts")
    try:
        body = claim_recovery(db, payload.model_dump(), _client_ip(request))
        db.commit()
    except RecoveryError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return body


@router.post("/recovery/restore")
def post_restore(payload: RecoveryRestoreIn, request: Request, db: Session = Depends(get_db)):
    if auth_limiter.hit(f"recovery-restore:{_client_ip(request)}", limit=8, window_seconds=600):
        raise HTTPException(429, "Too many recovery attempts")
    try:
        body = restore_account(db, payload.model_dump(), _client_ip(request))
        db.commit()
    except RecoveryError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return body

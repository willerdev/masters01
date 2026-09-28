from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.api.v1.router import _client_ip
from app.core.database import get_db
from app.domain.rbac import allows
from app.services.asset_service import AssetError, asset_home, request_deposit, request_withdrawal

router = APIRouter()


class DepositIn(BaseModel):
    currency: str
    amount: Decimal


class WithdrawIn(BaseModel):
    currency: str
    amount: Decimal
    address: str


def _allow(principal: Principal) -> None:
    if allows(principal.roles, "payments.manage") or allows(principal.roles, "portal.investor"):
        return
    raise HTTPException(403, "Assets are available to the super admin and approved investors")


def _fail(exc: AssetError) -> None:
    raise HTTPException(exc.status, exc.detail) from exc


@router.get("/assets")
def get_assets(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _allow(principal)
    return asset_home(db, principal.user)


@router.post("/assets/deposits")
def post_deposit(payload: DepositIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _allow(principal)
    try:
        row = request_deposit(db, principal.user, payload.currency, payload.amount, _client_ip(request))
        db.commit()
    except AssetError as exc:
        db.rollback()
        _fail(exc)
    return row


@router.post("/assets/withdrawals")
def post_withdrawal(payload: WithdrawIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _allow(principal)
    try:
        row = request_withdrawal(db, principal.user, payload.currency, payload.amount, payload.address, _client_ip(request))
        db.commit()
    except AssetError as exc:
        db.rollback()
        _fail(exc)
    return row

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.api.v1.router import _client_ip
from app.core.database import get_db
from app.core.rate_limit import auth_limiter
from app.services.payment_service import PaymentError, create_payment, list_payments, provider_status, save_provider
from app.services.payment_service import apply_cryptomus_ipn, apply_nowpayments_ipn

router = APIRouter()


class PaymentCredentialsIn(BaseModel):
    api_key: str = ""
    api_url: str = ""
    ipn_secret: str = ""
    payout_email: str = ""
    payout_password: str = ""
    merchant_id: str = ""


class PaymentProviderIn(BaseModel):
    provider: str
    sandbox: bool = False
    credentials: PaymentCredentialsIn


class PaymentCreateIn(BaseModel):
    price_amount: Decimal
    price_currency: str = "USD"
    pay_currency: str = ""
    purpose: str = "deposit"
    description: str = Field(default="", max_length=240)


@router.get("/payments/provider")
def get_provider(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("payments.manage")
    return provider_status(db, principal.user.organization_id)


@router.put("/payments/provider")
def put_provider(
    payload: PaymentProviderIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    principal.require("payments.manage")
    if auth_limiter.hit(f"pay-provider:{principal.user.id}", limit=10, window_seconds=60):
        raise HTTPException(429, "Too many payment provider checks")
    try:
        body = save_provider(db, principal.user, payload.model_dump(), _client_ip(request))
        db.commit()
    except PaymentError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return body


@router.get("/payments")
def get_payments(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("payments.manage")
    return list_payments(db, principal.user.organization_id)


@router.post("/payments")
def post_payment(
    payload: PaymentCreateIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    principal.require("payments.manage")
    if auth_limiter.hit(f"pay-create:{principal.user.id}", limit=20, window_seconds=60):
        raise HTTPException(429, "Too many payment requests")
    try:
        body = create_payment(db, principal.user, payload.model_dump(), _client_ip(request))
        db.commit()
    except PaymentError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return body


@router.post("/payments/ipn/nowpayments/{organization_id}")
async def nowpayments_ipn(organization_id: UUID, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "Notification body must be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Notification body must be an object")
    try:
        result = apply_nowpayments_ipn(db, organization_id, body, request.headers.get("x-nowpayments-sig", ""))
        db.commit()
    except PaymentError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.post("/payments/ipn/cryptomus/{organization_id}")
async def cryptomus_ipn(organization_id: UUID, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "Notification body must be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Notification body must be an object")
    try:
        result = apply_cryptomus_ipn(db, organization_id, body)
        db.commit()
    except PaymentError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    return result

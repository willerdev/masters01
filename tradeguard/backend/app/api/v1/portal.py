from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.api.v1.router import _client_ip, _cookies, _user_payload
from app.core.database import get_db
from app.core.rate_limit import auth_limiter
from app.services.auth_service import AuthError
from app.services.portal_service import PortalError
from app.services.portal_service import (
    decide_application,
    decide_capital_request,
    ensure_join_code,
    investor_portal,
    join_firm,
    list_applications,
    list_capital_requests,
    portal_home,
    request_capital,
    rotate_join_code,
    trader_portal,
)

router = APIRouter()


class JoinIn(BaseModel):
    code: str
    email: EmailStr
    password: str
    full_name: str
    kind: str
    answers: dict = Field(default_factory=dict)


class DecisionIn(BaseModel):
    decision: str
    note: str = ""
    account_id: UUID | None = None


class CapitalIn(BaseModel):
    fund_id: UUID
    kind: str
    amount: Decimal


class InvestorWalletIn(BaseModel):
    fund_id: UUID
    label: str
    address: str


class InvestorMoveIn(BaseModel):
    direction: str
    amount: Decimal
    note: str = ""


def _fail(exc: Exception) -> None:
    status = getattr(exc, "status", 400)
    detail = getattr(exc, "detail", "Request failed")
    raise HTTPException(status, detail) from exc


@router.post("/join")
def post_join(payload: JoinIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if auth_limiter.hit(f"join:{_client_ip(request)}", limit=10, window_seconds=600):
        raise HTTPException(429, "Too many attempts")
    try:
        user, access, refresh = join_firm(
            db,
            code=payload.code,
            email=str(payload.email),
            password=payload.password,
            full_name=payload.full_name,
            kind=payload.kind,
            answers=payload.answers,
            ip=_client_ip(request),
        )
        db.commit()
    except (PortalError, AuthError) as exc:
        _fail(exc)
    _cookies(response, access, refresh)
    return {"access_token": access, "user": _user_payload(user, ["APPLICANT"])}


@router.get("/join-code")
def get_join_code(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    try:
        code = ensure_join_code(db, principal.user.organization_id)
        db.commit()
    except PortalError as exc:
        _fail(exc)
    return {"code": code}


@router.post("/join-code/rotate")
def post_join_code(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    code = rotate_join_code(db, principal.user.organization_id)
    db.commit()
    return {"code": code}


@router.get("/applications")
def get_applications(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    return {
        "applications": list_applications(db, principal.user),
        "capital_requests": list_capital_requests(db, principal.user),
    }


@router.post("/applications/{application_id}")
def post_application(application_id: UUID, payload: DecisionIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    try:
        row = decide_application(db, principal.user, application_id, payload.decision, payload.note, payload.account_id)
        db.commit()
    except PortalError as exc:
        _fail(exc)
    return row


@router.post("/capital-requests/{request_id}")
def post_capital(request_id: UUID, payload: DecisionIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    try:
        row = decide_capital_request(db, principal.user, request_id, payload.decision, payload.note)
        db.commit()
    except PortalError as exc:
        _fail(exc)
    return row


@router.get("/portal/home")
def get_home(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return portal_home(db, principal.user, principal.roles)


@router.get("/portal/investor")
def get_investor(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("portal.investor")
    return investor_portal(db, principal.user)


@router.post("/portal/investor/requests")
def post_investor_request(payload: CapitalIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("portal.investor")
    try:
        row = request_capital(db, principal.user, payload.fund_id, payload.kind, payload.amount)
        db.commit()
    except PortalError as exc:
        _fail(exc)
    return row


@router.post("/portal/investor/wallets")
def post_investor_wallet(payload: InvestorWalletIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("portal.investor")
    from app.services.wallet_service import WalletError, save_investor_wallet

    try:
        row = save_investor_wallet(db, principal.user, payload.fund_id, payload.label, payload.address)
        db.commit()
    except WalletError as exc:
        _fail(exc)
    return row


@router.post("/portal/investor/wallets/{wallet_id}/moves")
def post_investor_move(wallet_id: UUID, payload: InvestorMoveIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("portal.investor")
    from app.services.wallet_service import WalletError, investor_move

    try:
        row = investor_move(db, principal.user, wallet_id, payload.direction, payload.amount, payload.note)
        db.commit()
    except WalletError as exc:
        _fail(exc)
    return row


@router.get("/portal/trader")
def get_trader(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("portal.trader")
    return trader_portal(db, principal.user, principal.roles)

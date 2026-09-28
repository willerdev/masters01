from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.api.v1.router import _client_ip
from app.core.database import get_db
from app.services.fund_service import FundError
from app.services.wallet_service import WalletError
from app.services.fund_service import (
    accrue_fees,
    allocate_order,
    attach_account,
    create_fund,
    detach_account,
    fund_detail,
    list_funds,
    publish_nav,
    reconcile_fund,
    redeem,
    save_budget,
    save_guideline,
    save_strategy,
    save_trader,
    stop_fund,
    subscribe,
)

router = APIRouter()


class FundIn(BaseModel):
    name: str
    base_currency: str = "USD"
    management_fee_pct: Decimal = Decimal("0")
    performance_fee_pct: Decimal = Decimal("0")


class AccountIn(BaseModel):
    account_id: UUID


class SubscribeIn(BaseModel):
    name: str = ""
    email: EmailStr
    amount: Decimal


class RedeemIn(BaseModel):
    investor_id: UUID
    amount: Decimal


class GuidelineIn(BaseModel):
    name: str
    metric: str
    operator: str
    threshold: Decimal
    action: str = "block"


class BudgetIn(BaseModel):
    max_daily_risk_pct: Decimal


class StrategyIn(BaseModel):
    name: str
    symbols: str = ""
    max_positions: int = 5
    account_id: UUID


class TraderIn(BaseModel):
    name: str
    max_positions: int = 5
    account_id: UUID


class FundOrderIn(BaseModel):
    symbol: str
    side: str
    action: str = "open"
    volume: Decimal
    price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


class StopIn(BaseModel):
    confirm: str = Field(default="")


class WalletIn(BaseModel):
    label: str
    address: str


class WalletMoveIn(BaseModel):
    direction: str
    amount: Decimal
    note: str = ""


class WalletSettleIn(BaseModel):
    decision: str


def _call(fn):
    try:
        return fn()
    except (FundError, WalletError) as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.get("/funds")
def get_funds(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.read")
    return list_funds(db, principal.user)


@router.post("/funds")
def post_fund(payload: FundIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    fund = _call(lambda: create_fund(db, principal.user, payload.name, payload.base_currency, payload.management_fee_pct, payload.performance_fee_pct))
    db.commit()
    return {"id": str(fund.id), "name": fund.name}


@router.get("/funds/{fund_id}")
def get_fund(fund_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.read")
    return _call(lambda: fund_detail(db, principal.user, principal.roles, fund_id))


@router.post("/funds/{fund_id}/accounts")
def post_account(fund_id: UUID, payload: AccountIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    _call(lambda: attach_account(db, principal.user, principal.roles, fund_id, payload.account_id))
    db.commit()
    return {"ok": True}


@router.delete("/funds/{fund_id}/accounts/{account_id}")
def delete_account(fund_id: UUID, account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    _call(lambda: detach_account(db, principal.user, fund_id, account_id))
    db.commit()
    return {"ok": True}


@router.post("/funds/{fund_id}/nav")
def post_nav(fund_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: publish_nav(db, principal.user, fund_id))
    db.commit()
    return row


@router.post("/funds/{fund_id}/subscriptions")
def post_subscription(fund_id: UUID, payload: SubscribeIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: subscribe(db, principal.user, fund_id, payload.name, str(payload.email), payload.amount))
    db.commit()
    return row


@router.post("/funds/{fund_id}/redemptions")
def post_redemption(fund_id: UUID, payload: RedeemIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: redeem(db, principal.user, fund_id, payload.investor_id, payload.amount))
    db.commit()
    return row


@router.post("/funds/{fund_id}/fees")
def post_fees(fund_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    rows = _call(lambda: accrue_fees(db, principal.user, fund_id))
    db.commit()
    return rows


@router.post("/funds/{fund_id}/guidelines")
def post_guideline(fund_id: UUID, payload: GuidelineIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: save_guideline(db, principal.user, fund_id, payload.name, payload.metric, payload.operator, payload.threshold, payload.action))
    db.commit()
    return row


@router.post("/funds/{fund_id}/budget")
def post_budget(fund_id: UUID, payload: BudgetIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: save_budget(db, principal.user, fund_id, payload.max_daily_risk_pct))
    db.commit()
    return row


@router.post("/funds/{fund_id}/strategies")
def post_strategy(fund_id: UUID, payload: StrategyIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    symbols = [part.strip() for part in payload.symbols.split(",") if part.strip()]
    row = _call(lambda: save_strategy(db, principal.user, principal.roles, fund_id, payload.name, symbols, payload.max_positions, payload.account_id))
    db.commit()
    return row


@router.post("/funds/{fund_id}/traders")
def post_trader(fund_id: UUID, payload: TraderIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: save_trader(db, principal.user, principal.roles, fund_id, payload.name, payload.max_positions, payload.account_id))
    db.commit()
    return row


@router.post("/funds/{fund_id}/orders")
def post_order(fund_id: UUID, payload: FundOrderIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    row = _call(lambda: allocate_order(db, principal.user, principal.roles, fund_id, payload.model_dump()))
    db.commit()
    return row


@router.post("/funds/{fund_id}/reconcile")
def post_reconcile(fund_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.read")
    rows = _call(lambda: reconcile_fund(db, principal.user, fund_id))
    db.commit()
    return rows


@router.post("/funds/{fund_id}/wallets")
def post_wallet(fund_id: UUID, payload: WalletIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    from app.services.wallet_service import save_fund_wallet

    row = _call(lambda: save_fund_wallet(db, principal.user, fund_id, payload.label, payload.address))
    db.commit()
    return row


@router.post("/funds/{fund_id}/wallets/{wallet_id}/moves")
def post_wallet_move(fund_id: UUID, wallet_id: UUID, payload: WalletMoveIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    from app.services.wallet_service import admin_move

    row = _call(lambda: admin_move(db, principal.user, fund_id, wallet_id, payload.direction, payload.amount, payload.note))
    db.commit()
    return row


@router.post("/funds/{fund_id}/wallet-moves/{movement_id}")
def post_wallet_settle(fund_id: UUID, movement_id: UUID, payload: WalletSettleIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("funds.manage")
    from app.services.wallet_service import settle_movement

    row = _call(lambda: settle_movement(db, principal.user, fund_id, movement_id, payload.decision))
    db.commit()
    return row


@router.post("/funds/{fund_id}/stop")
def post_stop(fund_id: UUID, payload: StopIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("emergency.stop")
    rows = _call(lambda: stop_fund(db, principal.user, fund_id, payload.confirm, _client_ip(request)))
    db.commit()
    return rows

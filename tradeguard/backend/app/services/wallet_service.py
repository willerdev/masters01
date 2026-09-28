from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.models.entities import CustodyWallet, Fund, Investor, User, WalletMovement

_ADDRESS = re.compile(r"^[A-Za-z0-9]{26,128}$")
_MONEY = Decimal("0.00000001")
_MAX = Decimal("1000000000000")


class WalletError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def fund_wallets(db: Session, fund: Fund) -> dict:
    wallets = db.scalars(select(CustodyWallet).where(CustodyWallet.fund_id == fund.id).order_by(CustodyWallet.created_at.desc())).all()
    moves = db.scalars(select(WalletMovement).where(WalletMovement.fund_id == fund.id).order_by(WalletMovement.created_at.desc()).limit(40)).all()
    return {"wallets": [_wallet_payload(db, row) for row in wallets], "movements": [_move_payload(db, row) for row in moves]}


def save_fund_wallet(db: Session, user: User, fund_id: UUID, label: str, address: str) -> dict:
    fund = _fund(db, user, fund_id)
    row = CustodyWallet(
        organization_id=fund.organization_id,
        fund_id=fund.id,
        investor_id=None,
        owner="fund",
        label=_label(label),
        address=_address(db, fund.id, address),
        currency=fund.base_currency,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="wallet_saved",
        entity_type="custody_wallet",
        entity_id=str(row.id),
        after={"fund_id": str(fund.id), "address": row.address, "owner": "fund"},
    )
    return _wallet_payload(db, row)


def admin_move(db: Session, user: User, fund_id: UUID, wallet_id: UUID, direction: str, amount: Decimal, note: str = "") -> dict:
    fund = _fund(db, user, fund_id)
    wallet = _wallet(db, fund, wallet_id)
    if wallet.owner != "fund":
        raise WalletError(400, "Investor wallet movements stay pending until you post them")
    posted = _add_movement(db, user, wallet, direction, amount, "posted", note)
    return _move_payload(db, posted)


def settle_movement(db: Session, user: User, fund_id: UUID, movement_id: UUID, decision: str) -> dict:
    fund = _fund(db, user, fund_id)
    row = db.get(WalletMovement, movement_id)
    if row is None or row.fund_id != fund.id or row.organization_id != fund.organization_id:
        raise WalletError(404, "Wallet movement not found")
    if row.status != "pending":
        raise WalletError(400, "That movement is already settled")
    if decision not in {"post", "reject"}:
        raise WalletError(400, "Choose post or reject")
    if decision == "post" and row.direction == "withdraw" and row.amount > _available(db, row.wallet_id) + row.amount:
        raise WalletError(400, "That is more than this wallet has available")
    row.status = "posted" if decision == "post" else "rejected"
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="wallet_movement_settled",
        entity_type="wallet_movement",
        entity_id=str(row.id),
        after={"status": row.status, "direction": row.direction, "amount": format(row.amount, "f")},
    )
    return _move_payload(db, row)


def investor_movements(db: Session, user: User) -> list[dict]:
    investor = _investor(db, user)
    if investor is None:
        return []
    wallet_ids = list(
        db.scalars(select(CustodyWallet.id).where(CustodyWallet.organization_id == user.organization_id, CustodyWallet.investor_id == investor.id)).all()
    )
    if not wallet_ids:
        return []
    rows = db.scalars(select(WalletMovement).where(WalletMovement.wallet_id.in_(wallet_ids)).order_by(WalletMovement.created_at.desc()).limit(30)).all()
    return [_move_payload(db, row) for row in rows]


def investor_wallets(db: Session, user: User) -> list[dict]:
    investor = _investor(db, user)
    if investor is None:
        return []
    rows = db.scalars(
        select(CustodyWallet).where(CustodyWallet.organization_id == user.organization_id, CustodyWallet.investor_id == investor.id).order_by(CustodyWallet.created_at.desc())
    ).all()
    return [_wallet_payload(db, row) for row in rows]


def save_investor_wallet(db: Session, user: User, fund_id: UUID, label: str, address: str) -> dict:
    investor = _investor(db, user)
    if investor is None:
        raise WalletError(403, "An admin has to approve you as an investor first")
    fund = db.get(Fund, fund_id)
    if fund is None or fund.organization_id != user.organization_id or fund.status != "open":
        raise WalletError(404, "Fund not found")
    row = CustodyWallet(
        organization_id=fund.organization_id,
        fund_id=fund.id,
        investor_id=investor.id,
        owner="investor",
        label=_label(label),
        address=_address(db, fund.id, address),
        currency=fund.base_currency,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="wallet_saved",
        entity_type="custody_wallet",
        entity_id=str(row.id),
        after={"fund_id": str(fund.id), "address": row.address, "owner": "investor"},
    )
    return _wallet_payload(db, row)


def investor_move(db: Session, user: User, wallet_id: UUID, direction: str, amount: Decimal, note: str = "") -> dict:
    investor = _investor(db, user)
    if investor is None:
        raise WalletError(403, "An admin has to approve you as an investor first")
    wallet = db.get(CustodyWallet, wallet_id)
    if wallet is None or wallet.organization_id != user.organization_id or wallet.investor_id != investor.id:
        raise WalletError(404, "Wallet not found")
    if direction == "withdraw":
        cash = _money(amount)
        if cash > _available(db, wallet.id):
            raise WalletError(400, "That is more than this wallet has available")
    row = _add_movement(db, user, wallet, direction, amount, "pending", note)
    return _move_payload(db, row)


def _add_movement(db: Session, user: User, wallet: CustodyWallet, direction: str, amount: Decimal, status: str, note: str) -> WalletMovement:
    if direction not in {"deposit", "withdraw"}:
        raise WalletError(400, "Choose deposit or withdraw")
    cash = _money(amount)
    if direction == "withdraw" and status == "posted" and cash > _available(db, wallet.id):
        raise WalletError(400, "That is more than this wallet has available")
    text = str(note or "").strip()[:240]
    row = WalletMovement(
        organization_id=wallet.organization_id,
        fund_id=wallet.fund_id,
        wallet_id=wallet.id,
        direction=direction,
        amount=cash,
        status=status,
        note=text,
        actor_user_id=user.id,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="wallet_movement",
        entity_type="wallet_movement",
        entity_id=str(row.id),
        after={"direction": direction, "amount": format(cash, "f"), "status": status, "address": wallet.address},
    )
    return row


def _available(db: Session, wallet_id: UUID) -> Decimal:
    total = Decimal("0")
    rows = db.scalars(select(WalletMovement).where(WalletMovement.wallet_id == wallet_id)).all()
    for row in rows:
        if row.direction == "deposit" and row.status == "posted":
            total += row.amount
        elif row.direction == "withdraw" and row.status in {"posted", "pending"}:
            total -= row.amount
    return total


def _wallet_payload(db: Session, row: CustodyWallet) -> dict:
    investor = None if row.investor_id is None else db.get(Investor, row.investor_id)
    fund = db.get(Fund, row.fund_id)
    return {
        "id": str(row.id),
        "fund_id": str(row.fund_id),
        "fund": "" if fund is None else fund.name,
        "owner": row.owner,
        "investor": "" if investor is None else investor.name,
        "label": row.label,
        "address": row.address,
        "currency": row.currency,
        "available": format(_available(db, row.id), "f"),
    }


def _move_payload(db: Session, row: WalletMovement) -> dict:
    wallet = db.get(CustodyWallet, row.wallet_id)
    return {
        "id": str(row.id),
        "wallet_id": str(row.wallet_id),
        "label": "" if wallet is None else wallet.label,
        "address": "" if wallet is None else wallet.address,
        "owner": "" if wallet is None else wallet.owner,
        "direction": row.direction,
        "amount": format(row.amount, "f"),
        "currency": "" if wallet is None else wallet.currency,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


def _fund(db: Session, user: User, fund_id: UUID) -> Fund:
    fund = db.get(Fund, fund_id)
    if fund is None or fund.organization_id != user.organization_id:
        raise WalletError(404, "Fund not found")
    return fund


def _wallet(db: Session, fund: Fund, wallet_id: UUID) -> CustodyWallet:
    row = db.get(CustodyWallet, wallet_id)
    if row is None or row.fund_id != fund.id:
        raise WalletError(404, "Wallet not found")
    return row


def _investor(db: Session, user: User) -> Investor | None:
    return db.scalar(select(Investor).where(Investor.organization_id == user.organization_id, Investor.user_id == user.id))


def _label(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80:
        raise WalletError(400, "Enter a wallet name")
    return text


def _address(db: Session, fund_id: UUID, value: str) -> str:
    text = str(value or "").strip()
    if _ADDRESS.fullmatch(text) is None:
        raise WalletError(400, "Enter a saved wallet address of letters and numbers, 26 to 128 characters")
    taken = db.scalar(select(CustodyWallet).where(CustodyWallet.fund_id == fund_id, CustodyWallet.address == text))
    if taken is not None:
        raise WalletError(400, "That address is already saved on this fund")
    return text


def _money(amount: Decimal) -> Decimal:
    try:
        cash = Decimal(amount).quantize(_MONEY)
    except Exception as exc:  # noqa: BLE001
        raise WalletError(400, "Enter an amount") from exc
    if cash <= 0 or cash > _MAX:
        raise WalletError(400, "Enter an amount greater than zero")
    return cash

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.database import get_db
from app.services.account_service import AccountError, get_visible_account, visible_account_query
from app.services.journal_service import account_journal

router = APIRouter()


@router.get("/journal")
def get_journal(
    account_id: UUID = Query(...),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    principal.require("accounts.read")
    try:
        account = get_visible_account(db, principal.user, principal.roles, account_id)
    except AccountError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    body = account_journal(db, account)
    db.commit()
    return body


@router.get("/journal/accounts")
def journal_accounts(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    rows = db.scalars(visible_account_query(db, principal.user, principal.roles)).all()
    return [{"id": str(row.id), "display_name": row.display_name, "account_number": row.account_number, "currency": row.currency} for row in rows]

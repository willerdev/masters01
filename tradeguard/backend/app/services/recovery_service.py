from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, new_token, sha256_hex, verify_password
from app.domain.audit import write_audit
from app.models.entities import AccountRecovery, MfaFactor, Session as DeskSession, User
from app.services.auth_service import password_is_strong

_TRC20 = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
_MISMATCH = "Recovery details did not match"
_dummy_hash: str | None = None


class RecoveryError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def recovery_status(db: Session, organization_id) -> dict:
    row = _row(db, organization_id)
    if row is None:
        return {
            "configured": False,
            "email": "",
            "trc20_wallet": "",
            "next_of_kin_name": "",
            "second_next_of_kin_name": "",
            "password_set": False,
            "updated_at": None,
            "restored_at": None,
        }
    return _public(row)


def save_recovery(db: Session, user: User, payload: dict, ip: str) -> dict:
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    confirm = str(payload.get("confirm_password") or "")
    wallet = str(payload.get("trc20_wallet") or "").strip()
    kin = _name(payload.get("next_of_kin_name"), "Enter the next of kin name")
    second = _name(payload.get("second_next_of_kin_name"), "Enter the second next of kin name")
    if "@" not in email or len(email) > 320:
        raise RecoveryError(400, "Enter a recovery email")
    if password != confirm:
        raise RecoveryError(400, "Recovery password and confirmation do not match")
    if not password_is_strong(password):
        raise RecoveryError(400, "Recovery password must be at least 12 characters and include a letter and a digit")
    if not _TRC20.fullmatch(wallet):
        raise RecoveryError(400, "Enter a TRC20 wallet address")
    if kin.casefold() == second.casefold():
        raise RecoveryError(400, "The second next of kin must be a different person")
    row = _row(db, user.organization_id)
    if row is None:
        row = AccountRecovery(organization_id=user.organization_id, user_id=user.id, email=email, password_hash="", trc20_wallet=wallet, next_of_kin_name=kin, second_next_of_kin_name=second)
        db.add(row)
    row.user_id = user.id
    row.email = email
    row.password_hash = hash_password(password)
    row.trc20_wallet = wallet
    row.next_of_kin_name = kin
    row.second_next_of_kin_name = second
    row.claim_token_hash = None
    row.claim_token_expires_at = None
    row.updated_at = datetime.now(timezone.utc)
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="recovery_saved",
        entity_type="account_recovery",
        entity_id=str(user.organization_id),
        after={"email": email, "trc20_wallet": wallet, "next_of_kin_name": kin, "second_next_of_kin_name": second},
        ip_address=ip,
    )
    db.flush()
    return _public(row)


def claim_recovery(db: Session, payload: dict, ip: str) -> dict:
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    wallet = str(payload.get("trc20_wallet") or "").strip()
    kin = _fold(payload.get("next_of_kin_name"))
    second = _fold(payload.get("second_next_of_kin_name"))
    row = db.scalar(select(AccountRecovery).where(AccountRecovery.email == email))
    if row is None:
        _burn_password(password)
        raise RecoveryError(401, _MISMATCH)
    if not _password_matches(row.password_hash, password):
        raise RecoveryError(401, _MISMATCH)
    matched = wallet == row.trc20_wallet and kin == _fold(row.next_of_kin_name) and second == _fold(row.second_next_of_kin_name)
    if not matched or not kin or not second:
        raise RecoveryError(401, _MISMATCH)
    token = new_token()
    now = datetime.now(timezone.utc)
    row.claim_token_hash = sha256_hex(token)
    row.claim_token_expires_at = now + timedelta(minutes=10)
    write_audit(
        db,
        organization_id=row.organization_id,
        actor_user_id=row.user_id,
        action="recovery_claimed",
        entity_type="account_recovery",
        entity_id=str(row.organization_id),
        after={"second_next_of_kin_name": row.second_next_of_kin_name},
        ip_address=ip,
    )
    return {"recovery_token": token, "expires_in": 600}


def restore_account(db: Session, payload: dict, ip: str) -> dict:
    token = str(payload.get("recovery_token") or "")
    new_password = str(payload.get("new_password") or "")
    if not password_is_strong(new_password):
        raise RecoveryError(400, "New desk password must be at least 12 characters and include a letter and a digit")
    row = db.scalar(select(AccountRecovery).where(AccountRecovery.claim_token_hash == sha256_hex(token))) if token else None
    now = datetime.now(timezone.utc)
    if row is None or row.claim_token_expires_at is None or row.claim_token_expires_at < now:
        raise RecoveryError(401, "Recovery token is invalid or expired")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.organization_id != row.organization_id:
        raise RecoveryError(401, "Recovery token is invalid or expired")
    previous_name = user.full_name
    user.password_hash = hash_password(new_password)
    user.full_name = row.second_next_of_kin_name
    user.mfa_required = False
    for factor in db.scalars(select(MfaFactor).where(MfaFactor.user_id == user.id)).all():
        factor.enabled = False
    for session in db.scalars(select(DeskSession).where(DeskSession.user_id == user.id, DeskSession.revoked_at.is_(None))).all():
        session.revoked_at = now
    row.claim_token_hash = None
    row.claim_token_expires_at = None
    row.restored_at = now
    write_audit(
        db,
        organization_id=row.organization_id,
        actor_user_id=user.id,
        action="account_recovered",
        entity_type="user",
        entity_id=str(user.id),
        before={"full_name": previous_name},
        after={"full_name": user.full_name, "second_next_of_kin_name": row.second_next_of_kin_name, "mfa_disabled": True},
        ip_address=ip,
    )
    return {"ok": True, "sign_in_email": user.email, "manager_name": user.full_name}


def _row(db: Session, organization_id) -> AccountRecovery | None:
    return db.scalar(select(AccountRecovery).where(AccountRecovery.organization_id == organization_id))


def _public(row: AccountRecovery) -> dict:
    return {
        "configured": True,
        "email": row.email,
        "trc20_wallet": row.trc20_wallet,
        "next_of_kin_name": row.next_of_kin_name,
        "second_next_of_kin_name": row.second_next_of_kin_name,
        "password_set": True,
        "updated_at": None if row.updated_at is None else row.updated_at.isoformat(),
        "restored_at": None if row.restored_at is None else row.restored_at.isoformat(),
    }


def _name(value: object, message: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) < 2 or len(text) > 200:
        raise RecoveryError(400, message)
    return text


def _fold(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _password_matches(stored: str, password: str) -> bool:
    if not stored:
        _burn_password(password)
        return False
    return verify_password(password, stored)


def _burn_password(password: str) -> None:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("recovery-timing-placeholder")
    verify_password(password, _dummy_hash)

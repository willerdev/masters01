from __future__ import annotations

from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.encryption import decrypt_json, encrypt_json
from app.models.entities import AlertChannelConfig

_DOMAINS_URL = "https://api.resend.com/domains"


def email_credentials(db: Session, organization_id: UUID) -> tuple[str, str]:
    settings = get_settings()
    secret = _secret(db, organization_id)
    key = str(secret.get("resend_api_key") or settings.resend_api_key or "").strip()
    sender = str(secret.get("from") or settings.resend_from or "").strip()
    return key, sender


def email_status(db: Session, organization_id: UUID) -> dict:
    key, sender = email_credentials(db, organization_id)
    return {"provider": "resend", "configured": bool(key), "from": sender}


def save_email_settings(db: Session, organization_id: UUID, api_key: str, from_address: str) -> dict:
    key = api_key.strip()
    sender = from_address.strip()
    if sender and "@" not in sender:
        raise ValueError("From address needs an email on a domain verified in Resend")
    if key and (not key.startswith("re_") or len(key) < 8):
        raise ValueError("A Resend API key starts with re_")
    row = _row(db, organization_id)
    secret = _read(row)
    if key:
        secret["resend_api_key"] = key
    elif not secret.get("resend_api_key") and not get_settings().resend_api_key.strip():
        raise ValueError("Paste the Resend API key")
    if sender:
        secret["from"] = sender
    elif not str(secret.get("from") or "").strip() and not get_settings().resend_from.strip():
        raise ValueError("Add the from address on your verified domain")
    nonce, ciphertext = encrypt_json(secret)
    row.secret_nonce = nonce
    row.secret_ciphertext = ciphertext
    db.flush()
    return email_status(db, organization_id)


def resend_connected(api_key: str) -> bool:
    if not api_key:
        return False
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                _DOMAINS_URL,
                headers={"Authorization": f"Bearer {api_key}", "User-Agent": "TradeGuard"},
            )
    except httpx.HTTPError:
        return False
    if response.status_code < 300:
        return True
    if response.status_code == 401 and "restricted" in response.text.lower():
        return True
    return False


def _row(db: Session, organization_id: UUID) -> AlertChannelConfig:
    row = db.scalar(
        select(AlertChannelConfig).where(
            AlertChannelConfig.organization_id == organization_id,
            AlertChannelConfig.channel == "email",
        )
    )
    if row is None:
        row = AlertChannelConfig(organization_id=organization_id, channel="email", enabled=True)
        db.add(row)
        db.flush()
    return row


def _secret(db: Session, organization_id: UUID) -> dict:
    row = db.scalar(
        select(AlertChannelConfig).where(
            AlertChannelConfig.organization_id == organization_id,
            AlertChannelConfig.channel == "email",
        )
    )
    return _read(row)


def _read(row: AlertChannelConfig | None) -> dict:
    if row is None or not row.secret_nonce or not row.secret_ciphertext:
        return {}
    try:
        data = decrypt_json(row.secret_nonce, row.secret_ciphertext)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

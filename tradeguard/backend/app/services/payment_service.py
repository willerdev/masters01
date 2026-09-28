from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.payments import (
    PaymentProviderError,
    canonical_status,
    connector_for,
    cryptomus_signature_matches,
    nowpayments_signature_matches,
)
from app.core.config import get_settings
from app.core.encryption import decrypt_json, encrypt_json
from app.domain.audit import write_audit
from app.models.entities import CryptoPayment, PaymentProviderConfig, User

PURPOSES = {"subscription", "deposit", "other"}


class PaymentError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def provider_status(db: Session, organization_id) -> dict:
    row = _config(db, organization_id)
    if row is None:
        return {"configured": False, "provider": "", "sandbox": False, "enabled": False, "callback_url": ""}
    return {
        "configured": True,
        "provider": row.provider,
        "sandbox": row.sandbox,
        "enabled": row.enabled,
        "callback_url": _callback_url(row),
    }


def save_provider(
    db: Session,
    user: User,
    payload: dict,
    ip: str,
    *,
    client: httpx.Client | None = None,
) -> dict:
    provider = str(payload.get("provider") or "").strip().lower()
    connector = connector_for(provider)
    if connector is None:
        raise PaymentError(400, "Choose NOWPayments or Cryptomus")
    credentials = dict(payload.get("credentials") or {})
    sandbox = bool(payload.get("sandbox"))
    if provider == "cryptomus":
        sandbox = False
    probed = connector.probe(credentials, sandbox=sandbox, client=client)
    if not probed["ok"]:
        raise PaymentError(400, probed["detail"])
    stored = _public_credentials(provider, credentials)
    nonce, ciphertext = encrypt_json(stored)
    row = _config(db, user.organization_id)
    before = None if row is None else {"provider": row.provider, "sandbox": row.sandbox, "enabled": row.enabled}
    if row is None:
        row = PaymentProviderConfig(
            organization_id=user.organization_id,
            provider=provider,
            sandbox=sandbox,
            enabled=True,
            secret_nonce=nonce,
            secret_ciphertext=ciphertext,
        )
        db.add(row)
    else:
        row.provider = provider
        row.sandbox = sandbox
        row.enabled = True
        row.secret_nonce = nonce
        row.secret_ciphertext = ciphertext
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="payment_provider_saved",
        entity_type="payment_provider",
        entity_id=str(row.id),
        before=before,
        after={"provider": provider, "sandbox": sandbox, "enabled": True},
        ip_address=ip,
    )
    return provider_status(db, user.organization_id)


def create_payment(
    db: Session,
    user: User,
    payload: dict,
    ip: str,
    *,
    client: httpx.Client | None = None,
    amount_scale: Decimal = Decimal("0.01"),
) -> dict:
    row = _config(db, user.organization_id)
    if row is None or not row.enabled:
        raise PaymentError(400, "Connect NOWPayments or Cryptomus before requesting a crypto payment")
    amount = _amount(payload.get("price_amount"), amount_scale)
    currency = str(payload.get("price_currency") or "USD").strip().upper()
    if len(currency) < 2 or len(currency) > 20:
        raise PaymentError(400, "Enter a price currency")
    pay_currency = str(payload.get("pay_currency") or "").strip()
    purpose = str(payload.get("purpose") or "deposit").strip().lower()
    if purpose not in PURPOSES:
        raise PaymentError(400, "Purpose must be subscription, deposit, or other")
    description = str(payload.get("description") or "").strip()[:240]
    order_id = uuid4().hex
    connector = connector_for(row.provider)
    credentials = decrypt_json(row.secret_nonce, row.secret_ciphertext)
    try:
        created = connector.create_payment(
            credentials,
            sandbox=row.sandbox,
            price_amount=amount,
            price_currency=currency,
            pay_currency=pay_currency,
            order_id=order_id,
            description=description,
            callback_url=_callback_url(row),
            client=client,
        )
    except PaymentProviderError as exc:
        raise PaymentError(exc.status, exc.detail) from exc
    status = canonical_status(row.provider, created["provider_status"])
    if status == "paid":
        status = "confirming"
    payment = CryptoPayment(
        organization_id=user.organization_id,
        provider=row.provider,
        order_id=order_id,
        purpose=purpose,
        description=description,
        price_amount=amount,
        price_currency=currency,
        pay_currency=str(created.get("pay_currency") or pay_currency),
        pay_amount=_optional_amount(created.get("pay_amount")),
        pay_address=str(created.get("pay_address") or ""),
        invoice_url=str(created.get("invoice_url") or ""),
        provider_payment_id=str(created.get("provider_payment_id") or ""),
        provider_status=str(created.get("provider_status") or ""),
        status=status,
    )
    db.add(payment)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="crypto_payment_requested",
        entity_type="crypto_payment",
        entity_id=str(payment.id),
        after={"provider": row.provider, "order_id": order_id, "status": status, "purpose": purpose, "price_amount": str(amount), "price_currency": currency},
        ip_address=ip,
    )
    return _payment_payload(payment)


def list_payments(db: Session, organization_id) -> list[dict]:
    rows = db.scalars(
        select(CryptoPayment).where(CryptoPayment.organization_id == organization_id).order_by(CryptoPayment.created_at.desc())
    ).all()
    return [_payment_payload(row) for row in rows]


def apply_nowpayments_ipn(db: Session, organization_id, body: dict, signature: str) -> dict:
    row = _config(db, organization_id)
    if row is None or row.provider != "nowpayments" or not row.enabled:
        raise PaymentError(404, "Payment provider is not configured")
    credentials = decrypt_json(row.secret_nonce, row.secret_ciphertext)
    if not nowpayments_signature_matches(body, str(credentials.get("ipn_secret") or ""), signature):
        raise PaymentError(401, "Payment notification signature did not match")
    order_id = str(body.get("order_id") or "")
    if order_id:
        result = _apply_provider_update(db, row, order_id, str(body.get("payment_status") or ""), body)
        from app.services.asset_service import settle_asset_deposit

        settle_asset_deposit(db, row.organization_id, order_id, result["status"], body)
        return result
    from app.services.asset_service import settle_asset_payout

    settled = settle_asset_payout(db, row.organization_id, body)
    if settled is None:
        return {"status": "ignored", "reason": "unknown_order"}
    return settled


def apply_cryptomus_ipn(db: Session, organization_id, body: dict) -> dict:
    row = _config(db, organization_id)
    if row is None or row.provider != "cryptomus" or not row.enabled:
        raise PaymentError(404, "Payment provider is not configured")
    credentials = decrypt_json(row.secret_nonce, row.secret_ciphertext)
    if not cryptomus_signature_matches(body, str(credentials.get("api_key") or ""), str(body.get("sign") or "")):
        raise PaymentError(401, "Payment notification signature did not match")
    return _apply_provider_update(db, row, str(body.get("order_id") or ""), str(body.get("status") or body.get("payment_status") or ""), body)


def _apply_provider_update(db: Session, config: PaymentProviderConfig, order_id: str, raw_status: str, body: dict) -> dict:
    payment = db.scalar(
        select(CryptoPayment).where(CryptoPayment.organization_id == config.organization_id, CryptoPayment.order_id == order_id)
    )
    if payment is None:
        write_audit(
            db,
            organization_id=config.organization_id,
            actor_type="payment_provider",
            action="crypto_payment_unknown",
            entity_type="payment_provider",
            entity_id=str(config.id),
            after={"order_id": order_id, "provider_status": raw_status},
        )
        return {"status": "ignored", "reason": "unknown_order"}
    mapped = canonical_status(config.provider, raw_status)
    if mapped == "pending":
        mapped = payment.status
    before = payment.status
    payment.provider_status = raw_status
    payment.status = mapped
    address = body.get("pay_address") or body.get("address") or body.get("from")
    if address:
        payment.pay_address = str(address)
    pay_amount = body.get("pay_amount") or body.get("payer_amount") or body.get("payment_amount")
    parsed = _optional_amount(pay_amount)
    if parsed is not None:
        payment.pay_amount = parsed
    pay_currency = body.get("pay_currency") or body.get("payer_currency")
    if pay_currency:
        payment.pay_currency = str(pay_currency)
    provider_id = body.get("payment_id") or body.get("uuid")
    if provider_id:
        payment.provider_payment_id = str(provider_id)
    if before != payment.status:
        write_audit(
            db,
            organization_id=config.organization_id,
            actor_type="payment_provider",
            action="crypto_payment_updated",
            entity_type="crypto_payment",
            entity_id=str(payment.id),
            before={"status": before},
            after={"status": payment.status, "provider_status": raw_status},
        )
    return {"status": payment.status, "order_id": payment.order_id}


def _config(db: Session, organization_id) -> PaymentProviderConfig | None:
    return db.scalar(select(PaymentProviderConfig).where(PaymentProviderConfig.organization_id == organization_id))


def _callback_url(row: PaymentProviderConfig) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/api/v1/payments/ipn/{row.provider}/{row.organization_id}"


def _public_credentials(provider: str, credentials: dict) -> dict:
    if provider == "nowpayments":
        return {
            "api_key": str(credentials.get("api_key") or "").strip(),
            "api_url": str(credentials.get("api_url") or "").strip().rstrip("/"),
            "ipn_secret": str(credentials.get("ipn_secret") or "").strip(),
            "payout_email": str(credentials.get("payout_email") or "").strip(),
            "payout_password": str(credentials.get("payout_password") or ""),
        }
    return {"merchant_id": str(credentials.get("merchant_id") or "").strip(), "api_key": str(credentials.get("api_key") or "").strip()}


def _amount(value: object, scale: Decimal = Decimal("0.01")) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PaymentError(400, "Enter a payment amount") from exc
    if amount <= 0:
        raise PaymentError(400, "Payment amount must be positive")
    return amount.quantize(scale)


def _optional_amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _payment_payload(row: CryptoPayment) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "order_id": row.order_id,
        "purpose": row.purpose,
        "description": row.description,
        "price_amount": f"{row.price_amount:.2f}",
        "price_currency": row.price_currency,
        "pay_currency": row.pay_currency,
        "pay_amount": None if row.pay_amount is None else f"{row.pay_amount:.8f}",
        "pay_address": row.pay_address,
        "invoice_url": row.invoice_url,
        "provider_payment_id": row.provider_payment_id,
        "provider_status": row.provider_status,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "ledger_posted": False,
    }

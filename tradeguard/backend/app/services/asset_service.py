from __future__ import annotations

import re
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.payments import PaymentProviderError, connector_for
from app.core.encryption import decrypt_json
from app.domain.audit import write_audit
from app.models.entities import AssetTransfer, PaymentProviderConfig, User
from app.services.payment_service import PaymentError, _callback_url, create_payment

_COIN = re.compile(r"^[A-Za-z0-9]{2,20}$")
_ADDRESS = re.compile(r"^[A-Za-z0-9]{26,128}$")
_SCALE = Decimal("0.00000001")
_MAX = Decimal("1000000000000")
_POSTED = {"finished", "completed", "success"}
_FAILED = {"failed", "rejected", "expired", "refunded"}


class AssetError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def asset_home(db: Session, user: User) -> dict:
    config = _nowpayments(db, user, required=False)
    return {
        "configured": config is not None,
        "provider": "" if config is None else config.provider,
        "balances": _balances(db, user),
        "transfers": [_payload(row) for row in _rows(db, user)],
    }


def request_deposit(db: Session, user: User, currency: str, amount: Decimal, ip: str, *, client: httpx.Client | None = None) -> dict:
    _nowpayments(db, user, required=True)
    coin = _coin(currency)
    cash = _crypto(amount)
    try:
        payment = create_payment(
            db,
            user,
            {"price_amount": cash, "price_currency": coin, "pay_currency": coin, "purpose": "deposit", "description": f"Asset deposit {coin}"},
            ip,
            client=client,
            amount_scale=_SCALE,
        )
    except PaymentError as exc:
        raise AssetError(exc.status, exc.detail) from exc
    row = AssetTransfer(
        organization_id=user.organization_id,
        user_id=user.id,
        currency=coin,
        direction="deposit",
        amount=cash,
        status="pending",
        address=str(payment.get("pay_address") or ""),
        provider_id=str(payment.get("provider_payment_id") or ""),
        order_id=str(payment.get("order_id") or ""),
        invoice_url=str(payment.get("invoice_url") or ""),
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="asset_deposit_requested",
        entity_type="asset_transfer",
        entity_id=str(row.id),
        after={"currency": coin, "amount": format(cash, "f"), "status": "pending"},
        ip_address=ip,
    )
    return _payload(row)


def request_withdrawal(db: Session, user: User, currency: str, amount: Decimal, address: str, ip: str, *, client: httpx.Client | None = None) -> dict:
    config = _nowpayments(db, user, required=True)
    coin = _coin(currency)
    cash = _crypto(amount)
    destination = _address(address)
    if cash > _available(db, user, coin):
        raise AssetError(400, "That is more than this asset has available")
    connector = connector_for("nowpayments")
    credentials = decrypt_json(config.secret_nonce, config.secret_ciphertext)
    try:
        payout = connector.create_payout(
            credentials,
            sandbox=config.sandbox,
            address=destination,
            currency=coin,
            amount=cash,
            callback_url=_callback_url(config),
            client=client,
        )
    except PaymentProviderError as exc:
        raise AssetError(exc.status, exc.detail) from exc
    state = _payout_state(str(payout.get("provider_status") or ""))
    if state == "failed":
        raise AssetError(502, "NOWPayments rejected the payout")
    row = AssetTransfer(
        organization_id=user.organization_id,
        user_id=user.id,
        currency=coin,
        direction="withdraw",
        amount=cash,
        status="posted" if state == "posted" else "pending",
        address=destination,
        provider_id=str(payout.get("provider_id") or ""),
        order_id=str(payout.get("batch_id") or ""),
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="asset_withdrawal_requested",
        entity_type="asset_transfer",
        entity_id=str(row.id),
        after={"currency": coin, "amount": format(cash, "f"), "status": row.status, "address": destination},
        ip_address=ip,
    )
    return _payload(row)


def settle_asset_deposit(db: Session, organization_id, order_id: str, status: str, body: dict) -> None:
    row = db.scalar(
        select(AssetTransfer).where(
            AssetTransfer.organization_id == organization_id,
            AssetTransfer.order_id == order_id,
            AssetTransfer.direction == "deposit",
        )
    )
    if row is None or row.status != "pending":
        return
    if status in {"failed", "expired"}:
        row.status = "failed"
        return
    if status != "paid":
        return
    received = _received(body)
    if received is None or received <= 0:
        row.note = "NOWPayments marked this paid without a crypto amount"
        return
    row.amount = received
    coin = str(body.get("pay_currency") or body.get("payer_currency") or row.currency).strip().lower()
    if _COIN.fullmatch(coin):
        row.currency = coin
    address = body.get("pay_address") or body.get("address")
    if address:
        row.address = str(address)[:180]
    row.status = "posted"
    write_audit(
        db,
        organization_id=organization_id,
        actor_type="payment_provider",
        action="asset_deposit_posted",
        entity_type="asset_transfer",
        entity_id=str(row.id),
        after={"currency": row.currency, "amount": format(received, "f")},
    )


def settle_asset_payout(db: Session, organization_id, body: dict) -> dict | None:
    provider_id = str(body.get("id") or body.get("batch_withdrawal_id") or "")
    if not provider_id:
        return None
    row = db.scalar(
        select(AssetTransfer).where(
            AssetTransfer.organization_id == organization_id,
            AssetTransfer.provider_id == provider_id,
            AssetTransfer.direction == "withdraw",
        )
    )
    if row is None or row.status != "pending":
        return None
    state = _payout_state(str(body.get("status") or ""))
    if state == "pending":
        return {"status": "pending", "id": str(row.id)}
    row.status = state
    write_audit(
        db,
        organization_id=organization_id,
        actor_type="payment_provider",
        action="asset_withdrawal_updated",
        entity_type="asset_transfer",
        entity_id=str(row.id),
        after={"status": row.status},
    )
    return {"status": row.status, "id": str(row.id)}


def _balances(db: Session, user: User) -> list[dict]:
    seen: list[str] = []
    for row in _rows(db, user):
        if row.currency not in seen:
            seen.append(row.currency)
    balances = []
    for coin in seen:
        available = _available(db, user, coin)
        if available > 0:
            balances.append({"currency": coin, "available": format(available, "f")})
    return balances


def _available(db: Session, user: User, currency: str) -> Decimal:
    total = Decimal("0")
    rows = db.scalars(
        select(AssetTransfer).where(AssetTransfer.organization_id == user.organization_id, AssetTransfer.user_id == user.id, AssetTransfer.currency == currency)
    ).all()
    for row in rows:
        if row.direction == "deposit" and row.status == "posted":
            total += row.amount
        elif row.direction == "withdraw" and row.status in {"posted", "pending"}:
            total -= row.amount
    return total


def _rows(db: Session, user: User) -> list[AssetTransfer]:
    return list(
        db.scalars(
            select(AssetTransfer)
            .where(AssetTransfer.organization_id == user.organization_id, AssetTransfer.user_id == user.id)
            .order_by(AssetTransfer.created_at.desc())
            .limit(40)
        ).all()
    )


def _payload(row: AssetTransfer) -> dict:
    return {
        "id": str(row.id),
        "currency": row.currency,
        "direction": row.direction,
        "amount": format(row.amount, "f"),
        "status": row.status,
        "address": row.address,
        "invoice_url": row.invoice_url,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _nowpayments(db: Session, user: User, *, required: bool) -> PaymentProviderConfig | None:
    row = db.scalar(select(PaymentProviderConfig).where(PaymentProviderConfig.organization_id == user.organization_id))
    if row is None or not row.enabled or row.provider != "nowpayments":
        if required:
            raise AssetError(400, "Connect NOWPayments before moving crypto assets")
        return None
    return row


def _coin(value: str) -> str:
    text = str(value or "").strip().lower()
    if _COIN.fullmatch(text) is None:
        raise AssetError(400, "Enter the crypto ticker, such as btc or usdttrc20")
    return text


def _address(value: str) -> str:
    text = str(value or "").strip()
    if _ADDRESS.fullmatch(text) is None:
        raise AssetError(400, "Enter the wallet address that should receive the crypto")
    return text


def _crypto(amount: Decimal) -> Decimal:
    try:
        cash = Decimal(amount).quantize(_SCALE)
    except Exception as exc:  # noqa: BLE001
        raise AssetError(400, "Enter an amount") from exc
    if cash <= 0 or cash > _MAX:
        raise AssetError(400, "Enter an amount greater than zero")
    return cash


def _received(body: dict) -> Decimal | None:
    for key in ("actually_paid", "pay_amount", "payer_amount"):
        value = body.get(key)
        if value in (None, ""):
            continue
        try:
            return Decimal(str(value)).quantize(_SCALE)
        except Exception:  # noqa: BLE001
            continue
    return None


def _payout_state(raw: str) -> str:
    value = raw.strip().lower()
    if value in _POSTED:
        return "posted"
    if value in _FAILED:
        return "failed"
    return "pending"

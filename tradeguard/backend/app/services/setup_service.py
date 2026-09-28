from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_json, encrypt_json
from app.core.totp import generate_secret, otpauth_uri, verify_totp
from app.domain.audit import write_audit
from app.models.entities import Account, MfaFactor, Organization, User
from app.services.account_service import AccountError, create_account
from app.services.payment_service import PaymentError, save_provider

COUNTRIES: dict[str, str] = {
    "Kenya": "+254",
    "Uganda": "+256",
    "Tanzania": "+255",
    "Nigeria": "+234",
    "South Africa": "+27",
    "Egypt": "+20",
    "United Arab Emirates": "+971",
    "Saudi Arabia": "+966",
    "United Kingdom": "+44",
    "Ireland": "+353",
    "Germany": "+49",
    "France": "+33",
    "Spain": "+34",
    "Italy": "+39",
    "Netherlands": "+31",
    "Switzerland": "+41",
    "Sweden": "+46",
    "Norway": "+47",
    "Poland": "+48",
    "Turkey": "+90",
    "India": "+91",
    "Singapore": "+65",
    "Hong Kong": "+852",
    "Japan": "+81",
    "South Korea": "+82",
    "China": "+86",
    "Australia": "+61",
    "New Zealand": "+64",
    "United States": "+1",
    "Canada": "+1",
    "Brazil": "+55",
    "Mexico": "+52",
}

LANGUAGES = {
    "en": "English",
    "sw": "Swahili",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "pt": "Portuguese",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "hi": "Hindi",
}


class SetupError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def totp_enabled(db: Session, user_id: UUID) -> bool:
    row = _factor(db, user_id)
    return bool(row and row.enabled and row.secret_ciphertext)


def _factor(db: Session, user_id: UUID) -> MfaFactor | None:
    return db.scalar(select(MfaFactor).where(MfaFactor.user_id == user_id, MfaFactor.factor_type == "totp"))


def _secret(row: MfaFactor) -> str:
    if not row.secret_ciphertext or not row.secret_nonce:
        return ""
    return str(decrypt_json(row.secret_nonce, row.secret_ciphertext).get("secret") or "")


def ensure_pending_totp(db: Session, user: User) -> str:
    row = _factor(db, user.id)
    if row and row.enabled:
        return ""
    if row and row.secret_ciphertext:
        return _secret(row)
    secret = generate_secret()
    nonce, ciphertext = encrypt_json({"secret": secret})
    db.add(
        MfaFactor(
            user_id=user.id,
            factor_type="totp",
            secret_nonce=nonce,
            secret_ciphertext=ciphertext,
            enabled=False,
        )
    )
    db.flush()
    return secret


def verify_user_code(db: Session, user: User, code: str) -> bool:
    row = _factor(db, user.id)
    if row is None or not row.enabled:
        return False
    return verify_totp(_secret(row), code)


def _terminal_account(db: Session, organization_id: UUID) -> Account | None:
    return db.scalar(
        select(Account).where(
            Account.organization_id == organization_id,
            Account.connection_method.in_(("metaapi", "local_mt5")),
        )
    )


def status_payload(db: Session, user: User, *, include_secret: bool) -> dict:
    org = db.get(Organization, user.organization_id)
    factor = _factor(db, user.id)
    secret = ""
    if include_secret and (factor is None or not factor.enabled):
        secret = ensure_pending_totp(db, user)
    terminal = _terminal_account(db, org.id)
    return {
        "complete": org.setup_completed_at is not None,
        "country": org.country,
        "language": org.language,
        "phone_country_code": org.phone_country_code,
        "phone_number": org.phone_number,
        "admin_email": org.admin_email or user.email,
        "mfa_enabled": bool(factor and factor.enabled),
        "mfa_secret": secret,
        "mfa_uri": otpauth_uri(user.email, secret) if secret else "",
        "has_terminal_account": terminal is not None,
        "countries": [{"name": name, "dial": dial} for name, dial in COUNTRIES.items()],
        "languages": [{"code": code, "name": name} for code, name in LANGUAGES.items()],
    }


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _apply_profile(db: Session, user: User, payload: dict) -> Organization:
    country = str(payload.get("country") or "").strip()
    language = str(payload.get("language") or "").strip()
    if country not in COUNTRIES:
        raise SetupError(400, "Choose a country")
    if language not in LANGUAGES:
        raise SetupError(400, "Choose a language")
    dial = _digits(str(payload.get("phone_country_code") or COUNTRIES[country]))
    number = _digits(str(payload.get("phone_number") or ""))
    if not dial or len(dial) > 4:
        raise SetupError(400, "Enter a phone country code")
    if len(number) < 6 or len(number) > 15:
        raise SetupError(400, "Enter a phone number")
    email = str(payload.get("admin_email") or "").strip().lower()
    if "@" not in email or len(email) > 320:
        raise SetupError(400, "Enter the admin email")
    taken = db.scalar(select(User).where(User.email == email, User.id != user.id))
    if taken is not None:
        raise SetupError(409, "Admin email is already registered")
    org = db.get(Organization, user.organization_id)
    org.country = country
    org.language = language
    org.phone_country_code = f"+{dial}"
    org.phone_number = number
    org.admin_email = email
    user.email = email
    return org


def complete_setup(db: Session, user: User, roles: list[str], payload: dict, ip: str) -> dict:
    if db.get(Organization, user.organization_id).setup_completed_at is not None:
        raise SetupError(409, "Setup is already complete")
    code = str(payload.get("totp_code") or "")
    row = _factor(db, user.id)
    if row is None or row.enabled or not row.secret_ciphertext:
        raise SetupError(400, "Open setup again so Google Authenticator can be loaded")
    if not verify_totp(_secret(row), code):
        raise SetupError(401, "Google Authenticator code did not match")
    account_in = payload.get("account") or {}
    method = str(account_in.get("connection_method") or "")
    if method not in {"metaapi", "local_mt5"}:
        raise SetupError(400, "Choose MetaAPI or MetaTrader 5 on this device")
    credentials = dict(account_in.get("credentials") or {})
    if method == "metaapi" and not (str(credentials.get("token") or "").strip() and str(credentials.get("metaapi_account_id") or "").strip()):
        raise SetupError(400, "MetaAPI needs a token and an account id")
    if method == "local_mt5":
        login = str(credentials.get("login") or "").strip()
        password = str(credentials.get("password") or "")
        server = str(credentials.get("server") or "").strip()
        if not login or not password or not server:
            raise SetupError(400, "MetaTrader 5 needs login, password, and server. The terminal must be running on this computer.")
        credentials["login"] = login
        credentials["password"] = password
        credentials["server"] = server
    account_in["connection_method"] = method
    account_in["credentials"] = credentials
    try:
        account, secrets = create_account(db, user, roles, account_in, ip)
    except AccountError as exc:
        raise SetupError(exc.status, exc.detail) from exc
    payment = payload.get("payment")
    if payment:
        try:
            save_provider(db, user, payment, ip)
        except PaymentError as exc:
            raise SetupError(exc.status, exc.detail) from exc
    org = _apply_profile(db, user, payload)
    row.enabled = True
    user.mfa_required = True
    tested = {"ok": True, "status": "connected", "error_code": "", "detail": ""}
    org.setup_completed_at = datetime.now(timezone.utc)
    write_audit(
        db,
        organization_id=org.id,
        actor_user_id=user.id,
        action="setup_completed",
        entity_type="organization",
        entity_id=str(org.id),
        after={"country": org.country, "language": org.language, "connection_method": method, "mfa": "totp"},
        ip_address=ip,
    )
    return {"account": account, "webhook": secrets, "connection_test": tested}

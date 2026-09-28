from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encode_access_token, hash_password, new_token, sha256_hex, verify_password
from app.domain.audit import write_audit
from app.domain.rbac import ROLE_PERMISSIONS
from app.models.entities import Organization, PasswordResetToken, Permission, Role, RolePermission, Session, User, UserRole
from app.services.mailer import Mailer

_SLUG = re.compile(r"[^a-z0-9]+")


class AuthError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def password_is_strong(password: str) -> bool:
    return len(password) >= 12 and any(ch.isalpha() for ch in password) and any(ch.isdigit() for ch in password)


def ensure_rbac(db: Session) -> None:
    existing = {row.code: row for row in db.scalars(select(Role)).all()}
    permissions = {row.code: row for row in db.scalars(select(Permission)).all()}
    for code in sorted({item for values in ROLE_PERMISSIONS.values() for item in values if item != "*"}):
        if code not in permissions:
            row = Permission(code=code)
            db.add(row)
            permissions[code] = row
    db.flush()
    for code in ROLE_PERMISSIONS:
        if code not in existing:
            role = Role(code=code, description=code.replace("_", " ").title())
            db.add(role)
            existing[code] = role
    db.flush()
    for role_code, granted in ROLE_PERMISSIONS.items():
        role = existing[role_code]
        if "*" in granted:
            granted = set(permissions)
        for permission_code in granted:
            permission = permissions[permission_code]
            found = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if found is None:
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()


def _slug(name: str) -> str:
    base = _SLUG.sub("-", name.lower()).strip("-") or "firm"
    return f"{base[:48]}-{uuid4().hex[:6]}"


def role_codes_for(db: Session, user_id) -> list[str]:
    rows = db.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).all()
    return [row[0] for row in rows]


def register_user(db: Session, *, email: str, password: str, full_name: str, organization_name: str, ip: str) -> tuple[User, str, str]:
    ensure_rbac(db)
    if not password_is_strong(password):
        raise AuthError(400, "Password must be at least 12 characters and include a letter and a digit")
    normalized = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized)):
        raise AuthError(409, "Email is already registered")
    org = Organization(name=organization_name.strip() or "TradeGuard", slug=_slug(organization_name or normalized))
    db.add(org)
    db.flush()
    user = User(
        organization_id=org.id,
        email=normalized,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
    )
    db.add(user)
    db.flush()
    role = db.scalar(select(Role).where(Role.code == "SUPER_ADMIN"))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    from app.services.account_service import ensure_default_profile

    ensure_default_profile(db, org.id)
    write_audit(db, organization_id=org.id, actor_user_id=user.id, action="register", entity_type="user", entity_id=str(user.id), ip_address=ip)
    access, refresh = _issue_session(db, user, ["SUPER_ADMIN"], ip, "")
    return user, access, refresh


def login_user(db: Session, *, email: str, password: str, ip: str, user_agent: str) -> tuple[User, str, str, list[str]]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError(401, "Invalid email or password")
    roles = role_codes_for(db, user.id)
    from app.services.setup_service import totp_enabled

    if totp_enabled(db, user.id):
        write_audit(
            db,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            action="login_mfa_required",
            entity_type="user",
            entity_id=str(user.id),
            ip_address=ip,
        )
        return user, "", "", roles
    access, refresh = _issue_session(db, user, roles, ip, user_agent)
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="login", entity_type="user", entity_id=str(user.id), ip_address=ip)
    return user, access, refresh, roles


def finish_mfa_login(db: Session, raw_token: str, code: str, ip: str, user_agent: str) -> tuple[User, str, str, list[str]]:
    import jwt

    from app.core.security import decode_token
    from app.services.setup_service import verify_user_code

    try:
        payload = decode_token(raw_token)
    except jwt.PyJWTError as exc:
        raise AuthError(401, "Authentication code expired") from exc
    if payload.get("type") != "mfa" or not payload.get("sub"):
        raise AuthError(401, "Authentication code expired")
    user = db.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active or not verify_user_code(db, user, code):
        raise AuthError(401, "Invalid authentication code")
    roles = role_codes_for(db, user.id)
    access, refresh = _issue_session(db, user, roles, ip, user_agent)
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="login", entity_type="user", entity_id=str(user.id), ip_address=ip)
    return user, access, refresh, roles


def refresh_session(db: Session, raw_refresh: str, ip: str, user_agent: str) -> tuple[User, str, str, list[str]]:
    token_hash = sha256_hex(raw_refresh)
    session = db.scalar(select(Session).where(Session.refresh_token_hash == token_hash))
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None or session.expires_at < now:
        raise AuthError(401, "Session expired")
    session.revoked_at = now
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise AuthError(401, "Session expired")
    roles = role_codes_for(db, user.id)
    access, refresh = _issue_session(db, user, roles, ip, user_agent)
    return user, access, refresh, roles


def logout_user(db: Session, raw_refresh: str, user: User, ip: str, session_id=None) -> None:
    now = datetime.now(timezone.utc)
    if session_id is not None:
        current = db.get(Session, session_id)
        if current is not None and current.user_id == user.id and current.revoked_at is None:
            current.revoked_at = now
    if raw_refresh:
        session = db.scalar(select(Session).where(Session.refresh_token_hash == sha256_hex(raw_refresh)))
        if session and session.user_id == user.id and session.revoked_at is None:
            session.revoked_at = now
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="logout", entity_type="user", entity_id=str(user.id), ip_address=ip)


def request_password_reset(db: Session, mailer: Mailer, email: str) -> None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        return
    raw = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=sha256_hex(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    from app.services.email_service import email_credentials

    api_key, sender = email_credentials(db, user.organization_id)
    mailer.send(
        user.email,
        "Reset your TradeGuard password",
        f"Use this token to reset your password. It expires in 30 minutes.\n\n{raw}\n",
        api_key=api_key,
        sender=sender,
    )
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="password_reset_requested", entity_type="user", entity_id=str(user.id))


def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    if not password_is_strong(new_password):
        raise AuthError(400, "Password must be at least 12 characters and include a letter and a digit")
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256_hex(raw_token)))
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None or row.expires_at < now:
        raise AuthError(400, "Reset token is invalid or expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise AuthError(400, "Reset token is invalid or expired")
    user.password_hash = hash_password(new_password)
    row.used_at = now
    for session in db.scalars(select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))).all():
        session.revoked_at = now
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="password_reset_completed", entity_type="user", entity_id=str(user.id))


def create_member(db: Session, actor: User, *, email: str, password: str, full_name: str, role_code: str, ip: str) -> User:
    if role_code not in ROLE_PERMISSIONS:
        raise AuthError(400, "Unknown role")
    if not password_is_strong(password):
        raise AuthError(400, "Password must be at least 12 characters and include a letter and a digit")
    normalized = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized)):
        raise AuthError(409, "Email is already registered")
    user = User(
        organization_id=actor.organization_id,
        email=normalized,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
    )
    db.add(user)
    db.flush()
    role = db.scalar(select(Role).where(Role.code == role_code))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action="user_created",
        entity_type="user",
        entity_id=str(user.id),
        after={"email": normalized, "role": role_code},
        ip_address=ip,
    )
    return user


def _issue_session(db: Session, user: User, roles: list[str], ip: str, user_agent: str) -> tuple[str, str]:
    from app.core.config import get_settings

    settings = get_settings()
    refresh = new_token()
    session = Session(
        user_id=user.id,
        refresh_token_hash=sha256_hex(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        user_agent=user_agent[:300],
        ip_address=ip[:64],
    )
    db.add(session)
    db.flush()
    access = encode_access_token(user_id=user.id, organization_id=user.organization_id, roles=roles, session_id=session.id)
    return access, refresh

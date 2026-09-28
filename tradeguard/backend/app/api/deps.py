from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.domain.rbac import allows
from app.models.entities import Session as AuthSession
from app.models.entities import User
from app.services.auth_service import role_codes_for
from app.services.mailer import Mailer, MemoryMailer

_test_mailer: MemoryMailer | None = None


def set_test_mailer(mailer: MemoryMailer | None) -> None:
    global _test_mailer
    _test_mailer = mailer


def get_mailer() -> Mailer:
    return _test_mailer or Mailer()


@dataclass
class Principal:
    user: User
    roles: list[str]
    session_id: UUID | None = None

    def require(self, permission: str) -> None:
        if not allows(self.roles, permission):
            raise HTTPException(status_code=403, detail="Missing permission")


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.cookies.get("tg_access")


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.cookies.get("tg_access") and not request.headers.get("authorization"):
        if request.headers.get("x-tradeguard-request") != "1":
            raise HTTPException(status_code=403, detail="Missing request header")
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    if payload.get("type") != "access" or not payload.get("sid"):
        raise HTTPException(status_code=401, detail="Invalid session")
    user = db.get(User, UUID(str(payload["sub"])))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid session")
    if str(payload.get("org") or "") != str(user.organization_id):
        raise HTTPException(status_code=401, detail="Invalid session")
    session = db.get(AuthSession, UUID(str(payload["sid"])))
    now = datetime.now(timezone.utc)
    if session is None or session.user_id != user.id or session.revoked_at is not None or session.expires_at < now:
        raise HTTPException(status_code=401, detail="Invalid session")
    roles = role_codes_for(db, user.id)
    if not roles:
        raise HTTPException(status_code=403, detail="Missing permission")
    return Principal(user=user, roles=roles, session_id=session.id)

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.redaction import redact
from app.models.entities import AuditLog


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def write_audit(
    db: Session,
    *,
    organization_id: UUID,
    action: str,
    actor_user_id: UUID | None = None,
    actor_type: str = "user",
    entity_type: str = "",
    entity_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str = "",
    request_id: str = "",
) -> AuditLog:
    row = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=redact(_jsonable(before)) if before is not None else None,
        after=redact(_jsonable(after)) if after is not None else None,
        ip_address=ip_address,
        request_id=request_id,
    )
    db.add(row)
    return row

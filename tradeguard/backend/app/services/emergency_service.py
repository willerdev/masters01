from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connectors.registry import connector_for
from app.domain.audit import write_audit
from app.models.entities import Account, BrokerCommand, EmergencyAction, User
from app.services.account_service import load_credentials
from app.services.alert_service import raise_alert

CONFIRMATIONS = {
    "PAUSE_ACCOUNT": "PAUSE ACCOUNT",
    "RESUME_ACCOUNT": "RESUME ACCOUNT",
    "CLOSE_ALL_TRADES": "CLOSE ALL TRADES",
    "DISABLE_NEW_TRADES": "DISABLE NEW TRADES",
    "EMERGENCY_STOP": "EMERGENCY STOP",
}

PERMISSIONS = {
    "PAUSE_ACCOUNT": "emergency.pause",
    "RESUME_ACCOUNT": "emergency.pause",
    "CLOSE_ALL_TRADES": "emergency.close",
    "DISABLE_NEW_TRADES": "emergency.pause",
    "EMERGENCY_STOP": "emergency.stop",
}


class EmergencyError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def apply_emergency(db: Session, user: User, account: Account, action: str, confirm: str, ip: str) -> dict:
    expected = CONFIRMATIONS.get(action)
    if expected is None:
        raise EmergencyError(400, "Unknown emergency action")
    if confirm != expected:
        raise EmergencyError(400, f"Type {expected} to confirm")
    result = "accepted"
    detail: dict = {}
    if action == "PAUSE_ACCOUNT":
        account.control_state = "PAUSED"
    elif action == "RESUME_ACCOUNT":
        account.control_state = "ACTIVE"
    elif action == "DISABLE_NEW_TRADES":
        account.control_state = "NEW_TRADES_DISABLED"
        db.add(BrokerCommand(account_id=account.id, command="DISABLE_NEW_TRADES"))
    elif action == "CLOSE_ALL_TRADES":
        detail = _request_close(db, account)
        result = detail.get("mode", "accepted")
    elif action == "EMERGENCY_STOP":
        account.control_state = "EMERGENCY_STOP"
        detail = _request_close(db, account)
        db.add(BrokerCommand(account_id=account.id, command="EMERGENCY_STOP", detail=detail))
        result = "emergency_stop"
    db.add(
        EmergencyAction(
            account_id=account.id,
            actor_user_id=user.id,
            action=action,
            confirmation=confirm,
            result=result,
            detail=detail,
        )
    )
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="emergency_action",
        entity_type="account",
        entity_id=str(account.id),
        after={"action": action, "result": result, "control_state": account.control_state},
        ip_address=ip,
    )
    if account.monitoring_enabled or action == "EMERGENCY_STOP":
        raise_alert(
            db,
            organization_id=account.organization_id,
            account_id=account.id,
            alert_type=action.lower(),
            severity="EMERGENCY_STOP" if action == "EMERGENCY_STOP" else "WARNING",
            title=f"{expected} — {account.display_name}",
            body=f"{user.email} confirmed {expected}.",
            dedupe_key=f"{account.id}:{action}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            cooldown=__import__("datetime").timedelta(seconds=1),
        )
    return {"action": action, "control_state": account.control_state, "result": result, "detail": detail}


def _request_close(db: Session, account: Account) -> dict:
    adapter = connector_for(account.connection_method)
    credentials = load_credentials(db, account.id)
    if adapter and adapter.capabilities().can_close and credentials:
        closed = adapter.close_all(credentials)
        return {"mode": closed.mode, "accepted": closed.accepted, "closed_tickets": closed.closed_tickets, "error_code": closed.error_code}
    command = BrokerCommand(account_id=account.id, command="CLOSE_ALL_TRADES", detail={"mode": "queued_for_ea"})
    db.add(command)
    db.flush()
    return {"mode": "queued_for_ea", "accepted": True, "command_id": str(command.id)}

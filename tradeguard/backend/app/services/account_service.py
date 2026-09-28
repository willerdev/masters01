from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.registry import connector_for
from app.services.connection_probe import probe_connection
from app.core.encryption import decrypt_json, encrypt_json
from app.core.security import new_token, sha256_hex
from app.domain.audit import write_audit
from app.domain.rbac import allows
from app.domain.ruleset import DEFAULT_RULES
from app.models.entities import (
    Account,
    AccountConnection,
    AccountCredential,
    AccountGrant,
    AccountState,
    RiskProfile,
    RiskRule,
    User,
    WebhookEndpoint,
)

METHODS = {"metaapi", "local_mt5", "webhook"}


class AccountError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def ensure_default_profile(db: Session, organization_id: UUID) -> RiskProfile:
    profile = db.scalar(
        select(RiskProfile).where(
            RiskProfile.organization_id == organization_id,
            RiskProfile.is_default.is_(True),
            RiskProfile.account_id.is_(None),
        )
    )
    if profile:
        return profile
    profile = RiskProfile(organization_id=organization_id, name="Organization default", is_default=True)
    db.add(profile)
    db.flush()
    _fill_rules(db, profile.id)
    return profile


def ensure_account_profile(db: Session, account: Account) -> RiskProfile:
    profile = db.scalar(select(RiskProfile).where(RiskProfile.account_id == account.id))
    if profile:
        return profile
    profile = RiskProfile(
        organization_id=account.organization_id,
        account_id=account.id,
        name=f"{account.display_name} rules",
        is_default=False,
    )
    db.add(profile)
    db.flush()
    _fill_rules(db, profile.id)
    return profile


def _fill_rules(db: Session, profile_id: UUID) -> None:
    for code, value in DEFAULT_RULES.items():
        if isinstance(value, bool):
            db.add(RiskRule(profile_id=profile_id, code=code, bool_value=value, enabled=False))
        else:
            db.add(RiskRule(profile_id=profile_id, code=code, numeric_value=Decimal(value), enabled=False))


def ensure_rule_row(db: Session, profile_id: UUID, code: str) -> RiskRule:
    row = db.scalar(select(RiskRule).where(RiskRule.profile_id == profile_id, RiskRule.code == code))
    if row is not None:
        return row
    value = DEFAULT_RULES[code]
    if isinstance(value, bool):
        row = RiskRule(profile_id=profile_id, code=code, bool_value=value, enabled=False)
    else:
        row = RiskRule(profile_id=profile_id, code=code, numeric_value=Decimal(value), enabled=False)
    db.add(row)
    db.flush()
    return row


def visible_account_query(db: Session, user: User, roles: list[str]):
    query = select(Account).where(Account.organization_id == user.organization_id)
    if any(role in {"SUPER_ADMIN", "ADMIN", "RISK_MANAGER"} for role in roles) or allows(roles, "users.manage"):
        return query
    grant_ids = select(AccountGrant.account_id).where(AccountGrant.user_id == user.id)
    return query.where(Account.id.in_(grant_ids))


def get_visible_account(db: Session, user: User, roles: list[str], account_id: UUID) -> Account:
    account = db.scalar(visible_account_query(db, user, roles).where(Account.id == account_id))
    if account is None:
        raise AccountError(404, "Account not found")
    return account


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else "0"))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def create_account(db: Session, user: User, roles: list[str], payload: dict, ip: str) -> tuple[Account, dict | None]:
    method = payload["connection_method"]
    if method not in METHODS:
        raise AccountError(400, "Unsupported connection method")
    credentials = dict(payload.get("credentials") or {})
    found = None
    connected = False
    if method in {"metaapi", "local_mt5"}:
        probed = probe_connection(method, credentials)
        if not probed["ok"] or not probed.get("account"):
            raise AccountError(400, probed.get("detail") or "Connection check failed")
        found = probed["account"]
        if not str(found.get("account_number") or "").strip():
            raise AccountError(400, "The terminal did not return an account number")
        if method == "metaapi":
            credentials["region"] = probed["region"]
        display_name = str(found["display_name"]).strip() or str(found["account_number"])
        account_number = str(found["account_number"]).strip()
        broker = str(found.get("broker") or "").strip()
        server = str(found.get("server") or "").strip()
        currency = str(found.get("currency") or "USD").upper()
        leverage = str(found.get("leverage") or "100")
        connected = True
    else:
        display_name = str(payload.get("display_name") or "").strip()
        account_number = str(payload.get("account_number") or "").strip()
        if not display_name or not account_number:
            raise AccountError(400, "Webhook accounts need a display name and account number")
        broker = str(payload.get("broker") or "").strip()
        server = str(payload.get("server") or "").strip()
        currency = str(payload.get("currency") or "USD").upper()
        leverage = str(payload.get("leverage") or "100")
    now = datetime.now(timezone.utc)
    account = Account(
        organization_id=user.organization_id,
        display_name=display_name,
        broker=broker,
        server=server,
        account_number=account_number,
        connection_method=method,
        currency=currency,
        leverage=Decimal(str(leverage)),
        trading_day_timezone=payload.get("trading_day_timezone") or "UTC",
        status="connected" if connected else "pending",
    )
    db.add(account)
    db.flush()
    db.add(AccountGrant(account_id=account.id, user_id=user.id))
    state = AccountState(account_id=account.id)
    if found:
        state.balance = _money(found.get("balance"))
        state.equity = _money(found.get("equity"))
        state.margin = _money(found.get("margin"))
        state.free_margin = _money(found.get("free_margin"))
        level = found.get("margin_level")
        state.margin_level = None if level in (None, "") else _money(level)
        state.peak_equity = state.equity
        state.day_start_equity = state.equity
        state.as_of = now
    db.add(state)
    db.add(
        AccountConnection(
            account_id=account.id,
            method=method,
            status="connected" if connected else "pending",
            last_success_at=now if connected else None,
        )
    )
    ensure_account_profile(db, account)
    secret_bundle = None
    if credentials:
        nonce, ciphertext = encrypt_json(credentials)
        db.add(AccountCredential(account_id=account.id, nonce=nonce, ciphertext=ciphertext))
    if method == "webhook":
        secret_bundle = _issue_webhook(db, account)
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="account_created",
        entity_type="account",
        entity_id=str(account.id),
        after={"display_name": account.display_name, "method": method, "account_number": account.account_number},
        ip_address=ip,
    )
    return account, secret_bundle


def update_account(db: Session, user: User, account: Account, payload: dict, ip: str) -> Account:
    before = {"display_name": account.display_name, "broker": account.broker, "server": account.server}
    for field in ("display_name", "broker", "server", "trading_day_timezone"):
        if payload.get(field) is not None:
            setattr(account, field, str(payload[field]).strip())
    if payload.get("leverage") is not None:
        account.leverage = Decimal(str(payload["leverage"]))
    if "ai_trading_enabled" in payload:
        account.ai_trading_enabled = bool(payload["ai_trading_enabled"])
    if "risk_blocks_paused" in payload:
        account.risk_blocks_paused = bool(payload["risk_blocks_paused"])
    if payload.get("credentials"):
        nonce, ciphertext = encrypt_json(payload["credentials"])
        row = db.scalar(select(AccountCredential).where(AccountCredential.account_id == account.id))
        if row is None:
            db.add(AccountCredential(account_id=account.id, nonce=nonce, ciphertext=ciphertext))
        else:
            row.nonce = nonce
            row.ciphertext = ciphertext
            row.rotated_at = datetime.now(timezone.utc)
    account.updated_at = datetime.now(timezone.utc)
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="account_updated",
        entity_type="account",
        entity_id=str(account.id),
        before=before,
        after={
            "display_name": account.display_name,
            "broker": account.broker,
            "server": account.server,
            "ai_trading_enabled": account.ai_trading_enabled,
            "risk_blocks_paused": account.risk_blocks_paused,
        },
        ip_address=ip,
    )
    return account


def load_credentials(db: Session, account_id: UUID) -> dict:
    row = db.scalar(select(AccountCredential).where(AccountCredential.account_id == account_id))
    if row is None:
        return {}
    return decrypt_json(row.nonce, row.ciphertext)


def set_monitoring(db: Session, user: User, account: Account, enabled: bool, ip: str) -> Account:
    account.monitoring_enabled = enabled
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="monitoring_changed",
        entity_type="account",
        entity_id=str(account.id),
        after={"monitoring_enabled": enabled},
        ip_address=ip,
    )
    return account


def connect_account(db: Session, user: User, account: Account, ip: str) -> Account:
    account.status = "pending"
    connection = _connection(db, account)
    connection.status = "pending"
    endpoint = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.account_id == account.id))
    if endpoint:
        endpoint.enabled = True
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="account_connect",
        entity_type="account",
        entity_id=str(account.id),
        ip_address=ip,
    )
    return account


def disconnect_account(db: Session, user: User, account: Account, ip: str) -> Account:
    account.status = "disconnected"
    connection = _connection(db, account)
    connection.status = "disconnected"
    endpoint = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.account_id == account.id))
    if endpoint:
        endpoint.enabled = False
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="account_disconnect",
        entity_type="account",
        entity_id=str(account.id),
        ip_address=ip,
    )
    return account


def test_connection(db: Session, user: User, account: Account, ip: str) -> dict:
    connection = _connection(db, account)
    if account.connection_method == "webhook":
        if connection.last_heartbeat_at is None:
            result = {"ok": False, "status": "waiting_for_heartbeat", "error_code": "no_heartbeat"}
        else:
            age = (datetime.now(timezone.utc) - connection.last_heartbeat_at).total_seconds()
            fresh = age <= 90
            result = {"ok": fresh, "status": "connected" if fresh else "stale", "error_code": "" if fresh else "heartbeat_stale", "age_seconds": int(age)}
    else:
        adapter = connector_for(account.connection_method)
        credentials = load_credentials(db, account.id)
        tested = adapter.test_connection(credentials) if adapter else None
        if tested is None:
            result = {"ok": False, "status": "unsupported", "error_code": "unsupported_method"}
        else:
            result = {"ok": tested.ok, "status": tested.status, "error_code": tested.error_code, "detail": tested.detail}
            if tested.ok:
                account.status = "connected"
                connection.status = "connected"
                connection.last_success_at = datetime.now(timezone.utc)
                connection.last_error_code = ""
            else:
                connection.last_error_code = tested.error_code
                connection.status = "degraded"
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="account_connection_tested",
        entity_type="account",
        entity_id=str(account.id),
        after={"status": result["status"], "ok": result["ok"]},
        ip_address=ip,
    )
    return result


def rotate_webhook(db: Session, user: User, account: Account, ip: str) -> dict:
    if account.connection_method != "webhook":
        raise AccountError(400, "Webhook credentials belong to webhook accounts")
    endpoint = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.account_id == account.id))
    if endpoint:
        db.delete(endpoint)
        db.flush()
    bundle = _issue_webhook(db, account)
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="webhook_rotated",
        entity_type="account",
        entity_id=str(account.id),
        ip_address=ip,
    )
    return bundle


def _issue_webhook(db: Session, account: Account) -> dict:
    token = new_token(24)
    api_key = f"tg_{new_token(24)}"
    secret = new_token(32)
    nonce, ciphertext = encrypt_json({"secret": secret})
    db.add(
        WebhookEndpoint(
            account_id=account.id,
            token=token,
            api_key_hash=sha256_hex(api_key),
            secret_nonce=nonce,
            secret_ciphertext=ciphertext,
        )
    )
    return {
        "url_path": f"/api/v1/webhooks/mt5/{token}",
        "token": token,
        "api_key": api_key,
        "signing_secret": secret,
    }


def _connection(db: Session, account: Account) -> AccountConnection:
    connection = db.scalar(select(AccountConnection).where(AccountConnection.account_id == account.id))
    if connection is None:
        connection = AccountConnection(account_id=account.id, method=account.connection_method)
        db.add(connection)
        db.flush()
    return connection

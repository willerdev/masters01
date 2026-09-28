from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_mailer, get_principal
from app.core.config import get_settings
from app.core.rate_limit import auth_limiter
from app.core.database import get_db
from app.domain.ruleset import RULE_FIELDS, apply_rule_update
from app.models.entities import (
    AccountState,
    Alert,
    DailyStatistic,
    AlertChannelConfig,
    ApiKey,
    AuditLog,
    BrokerCommand,
    ClosedTrade,
    Notification,
    OvertradingRow,
    Position,
    RiskDecisionRow,
    RiskProfile,
    RiskRule,
    User,
)
from app.services.connection_probe import probe_connection
from app.services.account_service import (
    AccountError,
    connect_account,
    create_account,
    disconnect_account,
    ensure_rule_row,
    get_visible_account,
    rotate_webhook,
    set_monitoring,
    test_connection,
    update_account,
    visible_account_query,
)
from app.services.ai_service import analyze_account, save_ai_config
from app.services.alert_service import TelegramChannel, SmsChannel
from app.services.analytics_service import _health, charts, latest_quotes, summary
from tradeguard_risk.drawdown import current_drawdown_pct, daily_pnl
from app.core.security import encode_mfa_token, new_token, sha256_hex
from app.services.auth_service import (
    AuthError,
    create_member,
    finish_mfa_login,
    login_user,
    logout_user,
    refresh_session,
    register_user,
    request_password_reset,
    reset_password,
    role_codes_for,
)
from app.services.emergency_service import PERMISSIONS, EmergencyError, apply_emergency
from app.services.ingest_service import WebhookRejected, accept_webhook
from app.domain.audit import write_audit
from app.domain.rbac import allows

router = APIRouter()


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    organization_name: str = "TradeGuard"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MfaIn(BaseModel):
    mfa_token: str
    code: str


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str


class MemberIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    role: str = "VIEWER"


class AccountIn(BaseModel):
    display_name: str = ""
    account_number: str = ""
    broker: str = ""
    server: str = ""
    connection_method: str
    currency: str = "USD"
    leverage: Decimal = Decimal("100")
    trading_day_timezone: str = "UTC"
    credentials: dict | None = None


class AccountPatch(BaseModel):
    display_name: str | None = None
    broker: str | None = None
    server: str | None = None
    leverage: Decimal | None = None
    trading_day_timezone: str | None = None
    credentials: dict | None = None
    ai_trading_enabled: bool | None = None
    risk_blocks_paused: bool | None = None


class OrderIn(BaseModel):
    action: str
    symbol: str = ""
    side: str = ""
    volume: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    price: Decimal | None = None
    ticket: str = ""


class AiTradeIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class AiCloseIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=80)
    api_key: str = Field(min_length=1, max_length=500)


class TradingApiIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=80)
    api_secret: str = Field(min_length=1, max_length=500)
    bot_token: str = Field(min_length=1, max_length=200)


class TelegramSettingsIn(BaseModel):
    app_id: str = ""
    api_hash: str = ""
    bot_token: str = ""


class TelegramTestIn(BaseModel):
    bot_token: str = ""


class TelegramUserCodeIn(BaseModel):
    phone: str = Field(min_length=8, max_length=32)


class TelegramUserConfirmIn(BaseModel):
    code: str = Field(min_length=3, max_length=12)
    password: str = Field(default="", max_length=200)


class TelegramChatsIn(BaseModel):
    chat_ids: list[str] = Field(default_factory=list, max_length=30)


class TelegramAutoExecuteIn(BaseModel):
    enabled: bool


class MonitoringIn(BaseModel):
    enabled: bool


class RulesIn(BaseModel):
    risk_per_trade_pct: Decimal | None = None
    max_daily_loss_pct: Decimal | None = None
    max_total_drawdown_pct: Decimal | None = None
    max_trades_per_day: Decimal | None = None
    max_open_positions: Decimal | None = None
    max_lot: Decimal | None = None
    max_consecutive_losses: Decimal | None = None
    min_minutes_between_trades: Decimal | None = None
    allow_trading: bool | None = None
    max_exposure_pct: Decimal | None = None
    enabled: dict[str, bool] | None = None


class EmergencyIn(BaseModel):
    action: str
    confirm: str


class AiConfigIn(BaseModel):
    provider: str = "openai"
    model: str = ""
    temperature: Decimal = Decimal("0.2")
    max_tokens: int = 800
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""


class ChannelIn(BaseModel):
    channel: str
    enabled: bool = True
    destination: str = ""
    secret: str = ""


class EmailIn(BaseModel):
    api_key: str = ""
    from_address: str = ""


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["accounts.read"])


class ProbeIn(BaseModel):
    connection_method: str
    credentials: dict = Field(default_factory=dict)


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "")[:64]


def _plain(value, places: int | None = None) -> str:
    number = Decimal("0") if value is None else Decimal(value)
    if places is not None:
        return f"{number:.{places}f}"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _cookies(response: Response, access: str, refresh: str) -> None:
    settings = get_settings()
    response.set_cookie("tg_access", access, httponly=True, samesite="lax", secure=settings.cookie_secure, max_age=settings.access_token_minutes * 60, path="/")
    response.set_cookie("tg_refresh", refresh, httponly=True, samesite="lax", secure=settings.cookie_secure, max_age=settings.refresh_token_days * 86400, path="/")


def _clear_cookies(response: Response) -> None:
    response.delete_cookie("tg_access", path="/")
    response.delete_cookie("tg_refresh", path="/")


def _user_payload(user: User, roles: list[str]) -> dict:
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "organization_id": str(user.organization_id), "roles": roles}


def _account_payload(db: Session, account) -> dict:
    state = db.get(AccountState, account.id)
    return {
        "id": str(account.id),
        "display_name": account.display_name,
        "broker": account.broker,
        "server": account.server,
        "account_number": account.account_number,
        "connection_method": account.connection_method,
        "currency": account.currency,
        "leverage": str(account.leverage),
        "status": account.status,
        "monitoring_enabled": account.monitoring_enabled,
        "ai_trading_enabled": account.ai_trading_enabled,
        "risk_blocks_paused": account.risk_blocks_paused,
        "bot_token_set": bool(account.bot_token_hash),
        "control_state": account.control_state,
        "trading_day_timezone": account.trading_day_timezone,
        "last_sync_at": None if account.last_sync_at is None else account.last_sync_at.isoformat(),
        "balance": _plain(state.balance if state else 0, 2),
        "equity": _plain(state.equity if state else 0, 2),
        "margin": _plain(state.margin if state else 0, 2),
        "free_margin": _plain(state.free_margin if state else 0, 2),
        "margin_level": None if not state or state.margin_level is None else _plain(state.margin_level, 2),
        "stale": bool(state.stale) if state else False,
    }


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/auth/register")
def register(payload: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if auth_limiter.hit(f"register:{_client_ip(request)}", limit=10, window_seconds=600):
        raise HTTPException(429, "Too many attempts")
    try:
        user, access, refresh = register_user(
            db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            organization_name=payload.organization_name,
            ip=_client_ip(request),
        )
        db.commit()
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _cookies(response, access, refresh)
    return {"access_token": access, "user": _user_payload(user, ["SUPER_ADMIN"])}


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"login:{_client_ip(request)}"
    if auth_limiter.hit(key, limit=20, window_seconds=300):
        raise HTTPException(429, "Too many attempts")
    try:
        user, access, refresh, roles = login_user(db, email=payload.email, password=payload.password, ip=_client_ip(request), user_agent=request.headers.get("user-agent", ""))
        db.commit()
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    if not access:
        return {"mfa_required": True, "mfa_token": encode_mfa_token(user_id=user.id)}
    _cookies(response, access, refresh)
    return {"access_token": access, "user": _user_payload(user, roles)}


@router.post("/auth/mfa")
def confirm_mfa(payload: MfaIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if auth_limiter.hit(f"mfa:{_client_ip(request)}", limit=8, window_seconds=300):
        raise HTTPException(429, "Too many attempts")
    try:
        user, access, refresh, roles = finish_mfa_login(
            db,
            payload.mfa_token,
            payload.code,
            _client_ip(request),
            request.headers.get("user-agent", ""),
        )
        db.commit()
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _cookies(response, access, refresh)
    return {"access_token": access, "user": _user_payload(user, roles)}


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get("tg_refresh", "")
    try:
        user, access, refresh_token, roles = refresh_session(db, raw, _client_ip(request), request.headers.get("user-agent", ""))
        db.commit()
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _cookies(response, access, refresh_token)
    return {"access_token": access, "user": _user_payload(user, roles)}


@router.post("/auth/logout")
def logout(request: Request, response: Response, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    logout_user(db, request.cookies.get("tg_refresh", ""), principal.user, _client_ip(request), principal.session_id)
    db.commit()
    _clear_cookies(response)
    return {"ok": True}


@router.get("/auth/me")
def me(principal: Principal = Depends(get_principal)):
    return _user_payload(principal.user, principal.roles)


@router.post("/auth/forgot-password")
def forgot_password(payload: ResetRequestIn, request: Request, db: Session = Depends(get_db), mailer=Depends(get_mailer)):
    if auth_limiter.hit(f"reset:{_client_ip(request)}", limit=8, window_seconds=600):
        raise HTTPException(429, "Too many attempts")
    request_password_reset(db, mailer, payload.email)
    db.commit()
    return {"detail": "If the account exists, a reset message has been sent."}


@router.post("/auth/reset-password")
def reset_password_route(payload: ResetIn, db: Session = Depends(get_db)):
    try:
        reset_password(db, payload.token, payload.password)
        db.commit()
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return {"ok": True}


@router.get("/users")
def list_users(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    users = db.scalars(select(User).where(User.organization_id == principal.user.organization_id)).all()
    return [{"id": str(user.id), "email": user.email, "full_name": user.full_name, "roles": role_codes_for(db, user.id), "is_active": user.is_active} for user in users]


@router.post("/users")
def add_user(payload: MemberIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("users.manage")
    if payload.role == "SUPER_ADMIN" and "SUPER_ADMIN" not in principal.roles:
        raise HTTPException(403, "Only a super admin can grant SUPER_ADMIN")
    try:
        user = create_member(db, principal.user, email=payload.email, password=payload.password, full_name=payload.full_name, role_code=payload.role, ip=_client_ip(request))
        db.commit()
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return {"id": str(user.id), "email": user.email, "roles": [payload.role]}


@router.get("/dashboard/summary")
def dashboard_summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    return summary(db, principal.user, principal.roles)


@router.get("/dashboard/charts")
def dashboard_charts(account_id: UUID | None = None, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    return charts(db, principal.user, principal.roles, account_id)


@router.get("/accounts")
def list_accounts(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    rows = db.scalars(visible_account_query(db, principal.user, principal.roles)).all()
    return [_account_payload(db, row) for row in rows]


@router.post("/connections/probe")
def probe_terminal(payload: ProbeIn, principal: Principal = Depends(get_principal)):
    principal.require("accounts.connect")
    if auth_limiter.hit(f"probe:{principal.user.id}", limit=30, window_seconds=60):
        raise HTTPException(429, "Too many connection checks")
    if payload.connection_method not in {"metaapi", "local_mt5"}:
        raise HTTPException(400, "Choose MetaAPI or MetaTrader 5")
    return probe_connection(payload.connection_method, payload.credentials)


@router.post("/accounts")
def post_account(payload: AccountIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    try:
        account, secrets = create_account(db, principal.user, principal.roles, payload.model_dump(), _client_ip(request))
        db.commit()
    except AccountError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    body = _account_payload(db, account)
    if secrets:
        body["webhook"] = secrets
    return body


@router.get("/accounts/{account_id}")
def get_account(
    account_id: UUID,
    sync: bool = Query(False),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    sync_error = ""
    if sync and account.connection_method in {"metaapi", "local_mt5"} and get_settings().environment == "test":
        from app.services.live_trades import refresh_terminal

        error = refresh_terminal(db, account)
        db.commit()
        if error:
            sync_error = error["detail"]
    payload = _account_payload(db, account)
    payload["sync_error"] = sync_error
    if sync:
        rows = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
        payload["positions"] = [_position_payload(row) for row in rows]
    payload["open_position_count"] = db.scalar(
        select(func.count()).select_from(Position).where(Position.account_id == account.id, Position.status == "open")
    ) or 0
    latest = db.scalar(select(RiskDecisionRow).where(RiskDecisionRow.account_id == account.id).order_by(RiskDecisionRow.created_at.desc()))
    over = db.scalar(select(OvertradingRow).where(OvertradingRow.account_id == account.id).order_by(OvertradingRow.created_at.desc()))
    payload["latest_decision"] = None if latest is None else latest.decision
    payload["overtrading"] = None if over is None else {"state": over.state, "metrics": over.metrics}
    payload["quotes"] = latest_quotes(db, account)
    state = db.get(AccountState, account.id)
    equity = state.equity if state else Decimal("0")
    open_risk = db.scalar(
        select(func.coalesce(func.sum(Position.risk_amount), 0)).where(Position.account_id == account.id, Position.status == "open")
    ) or Decimal("0")
    if state is None:
        payload["today_pl"] = "0.00"
        payload["current_drawdown"] = "0.00"
        payload["trade_frequency"] = 0
    else:
        payload["today_pl"] = _plain(daily_pnl(state.day_start_equity, state.equity), 2)
        payload["current_drawdown"] = _plain(current_drawdown_pct(state.peak_equity, state.equity), 2)
        payload["trade_frequency"] = int(
            db.scalar(
                select(func.coalesce(func.sum(DailyStatistic.trade_count), 0)).where(
                    DailyStatistic.account_id == account.id,
                    DailyStatistic.trading_date == state.trading_date,
                )
            )
            or 0
        )
    payload["risk_utilization"] = "0.00" if equity <= 0 else f"{(open_risk / equity * Decimal('100')):.2f}"
    payload["account_health"] = _health(db, account, state)
    return payload


@router.patch("/accounts/{account_id}")
def patch_account(account_id: UUID, payload: AccountPatch, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    account = _account_or_404(db, principal, account_id)
    update_account(db, principal.user, account, payload.model_dump(exclude_none=True), _client_ip(request))
    db.commit()
    return _account_payload(db, account)


@router.post("/accounts/{account_id}/connect")
def connect(account_id: UUID, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.connect")
    account = _account_or_404(db, principal, account_id)
    connect_account(db, principal.user, account, _client_ip(request))
    db.commit()
    return _account_payload(db, account)


@router.post("/accounts/{account_id}/disconnect")
def disconnect(account_id: UUID, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.connect")
    account = _account_or_404(db, principal, account_id)
    disconnect_account(db, principal.user, account, _client_ip(request))
    db.commit()
    return _account_payload(db, account)


@router.post("/accounts/{account_id}/test-connection")
def test_conn(account_id: UUID, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.connect")
    account = _account_or_404(db, principal, account_id)
    result = test_connection(db, principal.user, account, _client_ip(request))
    db.commit()
    return result


@router.post("/accounts/{account_id}/monitoring")
def monitoring(account_id: UUID, payload: MonitoringIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    account = _account_or_404(db, principal, account_id)
    set_monitoring(db, principal.user, account, payload.enabled, _client_ip(request))
    db.commit()
    return _account_payload(db, account)


@router.post("/accounts/{account_id}/webhook/rotate")
def rotate(account_id: UUID, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("webhooks.manage")
    account = _account_or_404(db, principal, account_id)
    try:
        bundle = rotate_webhook(db, principal.user, account, _client_ip(request))
        db.commit()
    except AccountError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return bundle


@router.get("/accounts/{account_id}/risk-rules")
def get_rules(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("risk_rules.read")
    account = _account_or_404(db, principal, account_id)
    return _rules_payload(db, account)


@router.put("/accounts/{account_id}/risk-rules")
def put_rules(account_id: UUID, payload: RulesIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("risk_rules.write")
    account = _account_or_404(db, principal, account_id)
    profile = db.scalar(select(RiskProfile).where(RiskProfile.account_id == account.id))
    if profile is None:
        raise HTTPException(404, "Risk profile missing")
    before = _rules_payload(db, account)
    incoming = payload.model_dump(exclude_none=True)
    enabled = incoming.pop("enabled", None) or {}
    code_by_field = {field: code for code, field in RULE_FIELDS.items()}
    for field, value in incoming.items():
        code = code_by_field.get(field)
        if not code:
            continue
        apply_rule_update(ensure_rule_row(db, profile.id, code), value)
    if isinstance(enabled, dict):
        for field, flag in enabled.items():
            code = code_by_field.get(field)
            if not code:
                continue
            ensure_rule_row(db, profile.id, code).enabled = bool(flag)
    after = dict(incoming)
    if enabled:
        after["enabled"] = {str(key): bool(value) for key, value in enabled.items()}
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="risk_rules_updated",
        entity_type="account",
        entity_id=str(account.id),
        before=before,
        after=after,
        ip_address=_client_ip(request),
    )
    db.commit()
    return _rules_payload(db, account)


@router.get("/accounts/{account_id}/positions")
def positions(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    rows = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
    return [_position_payload(row) for row in rows]


@router.get("/accounts/{account_id}/trades")
def trades(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    rows = db.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account.id).order_by(ClosedTrade.close_time.desc())).all()
    return [_trade_payload(row) for row in rows]


@router.get("/trades")
def all_trades(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    from app.services.live_trades import connected_accounts, current_sync_errors, refresh_open_trades

    accounts = connected_accounts(db, principal.user, principal.roles)
    if get_settings().environment == "test":
        errors = refresh_open_trades(db, accounts)
        db.commit()
    else:
        errors = current_sync_errors(accounts)
    synced_at = max((account.last_sync_at for account in accounts if account.last_sync_at is not None), default=None)
    stamp = None if synced_at is None else synced_at.isoformat()
    ids = [account.id for account in accounts]
    names = {account.id: account.display_name for account in accounts}
    if not ids:
        return {"trades": [], "errors": errors, "synced_at": stamp}
    rows = db.scalars(select(Position).where(Position.account_id.in_(ids), Position.status == "open")).all()
    trades = []
    for row in rows:
        payload = _position_payload(row)
        payload["account_name"] = names.get(row.account_id, "")
        trades.append(payload)
    return {"trades": trades, "errors": errors, "synced_at": stamp}


@router.post("/accounts/{account_id}/emergency")
def emergency(account_id: UUID, payload: EmergencyIn, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    permission = PERMISSIONS.get(payload.action)
    if permission is None or not allows(principal.roles, permission):
        raise HTTPException(403, "Missing permission")
    account = _account_or_404(db, principal, account_id)
    try:
        result = apply_emergency(db, principal.user, account, payload.action, payload.confirm, _client_ip(request))
        db.commit()
    except EmergencyError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.get("/accounts/{account_id}/commands")
def commands(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    rows = db.scalars(select(BrokerCommand).where(BrokerCommand.account_id == account.id, BrokerCommand.status == "pending")).all()
    return [{"id": str(row.id), "command": row.command, "detail": row.detail, "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/alerts")
def alerts(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.read")
    rows = db.scalars(select(Alert).where(Alert.organization_id == principal.user.organization_id).order_by(Alert.created_at.desc()).limit(200)).all()
    return [{"id": str(row.id), "type": row.alert_type, "severity": row.severity, "title": row.title, "body": row.body, "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/notifications")
def notifications(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.read")
    rows = db.scalars(select(Notification).where(Notification.user_id == principal.user.id).order_by(Notification.created_at.desc()).limit(200)).all()
    return [{"id": str(row.id), "channel": row.channel, "title": row.title, "body": row.body, "status": row.status, "read_at": None if row.read_at is None else row.read_at.isoformat()} for row in rows]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    row = db.get(Notification, notification_id)
    if row is None or row.user_id != principal.user.id:
        raise HTTPException(404, "Notification not found")
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.put("/alert-channels")
def put_channel(payload: ChannelIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    if payload.channel not in {"email", "webhook", "telegram", "sms", "in_app"}:
        raise HTTPException(400, "Unknown channel")
    row = db.scalar(select(AlertChannelConfig).where(AlertChannelConfig.organization_id == principal.user.organization_id, AlertChannelConfig.channel == payload.channel))
    if row is None:
        row = AlertChannelConfig(organization_id=principal.user.organization_id, channel=payload.channel)
        db.add(row)
    row.enabled = payload.enabled
    row.destination = payload.destination
    if payload.secret:
        from app.core.encryption import decrypt_json, encrypt_json

        existing: dict = {}
        if row.secret_nonce and row.secret_ciphertext:
            try:
                loaded = decrypt_json(row.secret_nonce, row.secret_ciphertext)
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}
        existing["secret"] = payload.secret
        nonce, ciphertext = encrypt_json(existing)
        row.secret_nonce = nonce
        row.secret_ciphertext = ciphertext
    db.commit()
    return {"channel": row.channel, "enabled": row.enabled, "destination": row.destination}


@router.get("/email")
def get_email(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.read")
    from app.services.email_service import email_status

    return email_status(db, principal.user.organization_id)


@router.put("/email")
def put_email(payload: EmailIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.email_service import save_email_settings

    try:
        status = save_email_settings(db, principal.user.organization_id, payload.api_key, payload.from_address)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="email_config_updated",
        entity_type="alert_channel",
        entity_id="email",
        after={"provider": "resend", "configured": status["configured"], "from": status["from"]},
    )
    db.commit()
    return status


@router.post("/email/test")
def test_email(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.email_service import email_credentials
    from app.services.mailer import Mailer

    key, sender = email_credentials(db, principal.user.organization_id)
    if not key:
        raise HTTPException(400, "Save a Resend API key first")
    mailer = Mailer()
    status = mailer.send(
        principal.user.email,
        "TradeGuard email",
        "Resend is connected. Alert emails and password resets use this from address.",
        api_key=key,
        sender=sender,
    )
    if status != "sent":
        raise HTTPException(502, mailer.last_error or "Resend did not accept the message")
    return {"sent": True, "to": principal.user.email}


@router.get("/alert-channels/status")
def channel_status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.read")
    from app.services.email_service import email_credentials

    settings = get_settings()
    telegram = TelegramChannel()
    sms = SmsChannel()
    key, _sender = email_credentials(db, principal.user.organization_id)
    return {
        "email_configured": bool(key or settings.smtp_host),
        "telegram_configured": bool(settings.telegram_bot_token),
        "sms_configured": bool(settings.twilio_account_sid and settings.twilio_auth_token),
        "telegram_probe": telegram.send("", "probe")[0],
        "sms_probe": sms.send("", "probe")[0],
    }


@router.get("/audit-logs")
def audit_logs(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("audit.read")
    rows = db.scalars(select(AuditLog).where(AuditLog.organization_id == principal.user.organization_id).order_by(AuditLog.created_at.desc()).limit(300)).all()
    return [
        {
            "id": str(row.id),
            "action": row.action,
            "actor_type": row.actor_type,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "before": row.before,
            "after": row.after,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/integrations")
def integrations(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.read")
    from app.services.ai_service import integration_status

    return integration_status(db, principal.user.organization_id)


@router.put("/ai/config")
def ai_config(payload: AiConfigIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("ai.configure")
    try:
        row = save_ai_config(db, principal.user.organization_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    write_audit(db, organization_id=principal.user.organization_id, actor_user_id=principal.user.id, action="ai_config_updated", entity_type="ai_provider", entity_id=str(row.id), after={"provider": row.provider, "enabled": row.enabled})
    db.commit()
    return {"provider": row.provider, "model": row.model, "enabled": row.enabled, "temperature": str(row.temperature), "max_tokens": row.max_tokens}


@router.post("/accounts/{account_id}/orders")
def post_order(account_id: UUID, payload: OrderIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    account = _account_or_404(db, principal, account_id)
    from app.services.order_service import OrderError, place_order

    try:
        result = place_order(db, principal.user, account, payload.model_dump(), actor="user")
        db.commit()
    except OrderError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.get("/accounts/{account_id}/candles")
def candles(
    account_id: UUID,
    symbol: str = "",
    timeframe: str = "15m",
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    principal.require("accounts.read")
    account = _account_or_404(db, principal, account_id)
    if account.connection_method != "metaapi":
        raise HTTPException(400, "This connection cannot load broker candles")
    from app.connectors.metaapi import MetaApiConnector
    from app.services.account_service import load_credentials

    credentials = load_credentials(db, account.id)
    try:
        rows = MetaApiConnector().fetch_candles(credentials, symbol, timeframe, limit=300)
    except ValueError as exc:
        raise HTTPException(400, "Choose a symbol and a supported timeframe") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "Broker candles are not available") from exc
    return {"symbol": symbol, "timeframe": timeframe, "candles": rows}


@router.post("/accounts/{account_id}/trading-api")
def save_trading_api(account_id: UUID, payload: TradingApiIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    account = _account_or_404(db, principal, account_id)
    from app.services.order_service import OrderError, save_trading_contact

    try:
        result = save_trading_contact(db, principal.user, account, payload.app_id, payload.api_secret, payload.bot_token)
        db.commit()
    except OrderError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.get("/telegram")
def get_telegram(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.alert_service import telegram_settings

    return telegram_settings(db, principal.user.organization_id)


@router.put("/telegram")
def put_telegram(payload: TelegramSettingsIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.alert_service import TelegramError, save_telegram_settings

    try:
        result = save_telegram_settings(db, principal.user.organization_id, payload.app_id, payload.api_hash, payload.bot_token)
    except TelegramError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="telegram_settings_saved",
        entity_type="telegram",
        entity_id=str(principal.user.organization_id),
        after={"app_id_set": bool(result["app_id"]), "bot_token_set": result["bot_token_set"]},
    )
    db.commit()
    return result


@router.post("/telegram/test")
def telegram_test(payload: TelegramTestIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.alert_service import (
        TelegramError,
        apply_telegram_test_result,
        restore_webhook,
        send_bot_test,
        telegram_bot_token,
        telegram_paused_webhook,
    )

    token = payload.bot_token.strip() or telegram_bot_token(db, principal.user.organization_id)
    if not token:
        raise HTTPException(400, "Save the bot token, then press Send test.")
    try:
        result = send_bot_test(token, telegram_paused_webhook(db, principal.user.organization_id))
    except TelegramError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    paused = str(result.get("paused_webhook") or "")
    stored = apply_telegram_test_result(db, principal.user.organization_id, paused, result.get("chat_id"))
    if paused and not stored:
        restore_webhook(token, paused)
        raise HTTPException(400, "Save Telegram first, then press Send test.")
    db.commit()
    if not result.get("sent"):
        raise HTTPException(400, str(result.get("detail") or "Send a message to the bot, then press Send test again."))
    return {"sent": True, "bot": result.get("bot") or ""}


def _telegram_result(db: Session, action):
    from app.services.alert_service import TelegramError

    try:
        return action()
    except TelegramError as exc:
        db.commit()
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/telegram/user/code")
def telegram_user_code(payload: TelegramUserCodeIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.telegram_user import request_login_code

    result = _telegram_result(db, lambda: request_login_code(db, principal.user.organization_id, payload.phone))
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="telegram_login_code_sent",
        entity_type="telegram",
        entity_id=str(principal.user.organization_id),
        after={"sent": bool(result.get("sent")), "connected": bool(result.get("connected"))},
    )
    db.commit()
    return result


@router.post("/telegram/user/confirm")
def telegram_user_confirm(payload: TelegramUserConfirmIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.telegram_user import confirm_login

    result = _telegram_result(db, lambda: confirm_login(db, principal.user.organization_id, payload.code, payload.password))
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="telegram_user_connected",
        entity_type="telegram",
        entity_id=str(principal.user.organization_id),
        after={"connected": True},
    )
    db.commit()
    return result


@router.delete("/telegram/user")
def telegram_user_delete(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.telegram_user import forget_user

    result = forget_user(db, principal.user.organization_id)
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="telegram_user_disconnected",
        entity_type="telegram",
        entity_id=str(principal.user.organization_id),
        after={"connected": False},
    )
    db.commit()
    return result


@router.get("/telegram/signals")
def telegram_signals(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.telegram_user import list_pending_signals

    result = list_pending_signals(db, principal.user.organization_id)
    db.commit()
    return result


@router.put("/telegram/auto-execute")
def telegram_auto_execute(payload: TelegramAutoExecuteIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.alert_service import TelegramError
    from app.services.telegram_user import set_auto_execute

    try:
        result = set_auto_execute(db, principal.user.organization_id, payload.enabled)
    except TelegramError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="telegram_auto_execute",
        entity_type="telegram",
        entity_id=str(principal.user.organization_id),
        after={"enabled": result["auto_execute"]},
    )
    db.commit()
    return result


@router.post("/telegram/signals/{signal_id}/execute")
def telegram_signal_execute(signal_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.alert_service import TelegramError
    from app.services.telegram_user import execute_pending_signal

    try:
        result = execute_pending_signal(db, principal.user.organization_id, signal_id)
    except TelegramError as exc:
        db.commit()
        raise HTTPException(exc.status, exc.detail) from exc
    db.commit()
    return result


@router.get("/telegram/chats")
def telegram_chats(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.telegram_user import list_chats

    result = _telegram_result(db, lambda: list_chats(db, principal.user.organization_id))
    db.commit()
    return result


@router.put("/telegram/chats")
def telegram_chats_save(payload: TelegramChatsIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("alerts.manage")
    from app.services.telegram_user import save_copy_chats

    result = _telegram_result(db, lambda: save_copy_chats(db, principal.user.organization_id, payload.chat_ids))
    write_audit(
        db,
        organization_id=principal.user.organization_id,
        actor_user_id=principal.user.id,
        action="telegram_copy_chats_saved",
        entity_type="telegram",
        entity_id=str(principal.user.organization_id),
        after={"count": len(result.get("chats") or [])},
    )
    db.commit()
    return result


@router.post("/bot/close")
def bot_close(request: Request, db: Session = Depends(get_db)):
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else (request.headers.get("x-bot-token") or "").strip()
    from app.services.order_service import OrderError, close_with_bot_token

    try:
        result = close_with_bot_token(db, token)
        db.commit()
    except OrderError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.post("/accounts/{account_id}/ai/close")
def ai_close(account_id: UUID, payload: AiCloseIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("accounts.write")
    account = _account_or_404(db, principal, account_id)
    from app.services.order_service import OrderError, close_ai_trading

    try:
        result = close_ai_trading(db, principal.user, account, payload.app_id, payload.api_key)
        db.commit()
    except OrderError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.post("/accounts/{account_id}/ai/trade")
def ai_trade(account_id: UUID, payload: AiTradeIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("ai.invoke")
    account = _account_or_404(db, principal, account_id)
    from app.services.ai_service import run_trade_assistant
    from app.services.order_service import OrderError

    try:
        result = run_trade_assistant(db, principal.user, account, payload.message)
        db.commit()
    except OrderError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return result


@router.post("/accounts/{account_id}/ai/analyze")
def ai_analyze(account_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("ai.invoke")
    account = _account_or_404(db, principal, account_id)
    result = analyze_account(db, principal.user, account)
    db.commit()
    return result


@router.post("/api-keys")
def create_key(payload: ApiKeyIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("api_keys.manage")
    raw = f"tgk_{new_token(24)}"
    row = ApiKey(organization_id=principal.user.organization_id, name=payload.name, prefix=raw[:10], key_hash=sha256_hex(raw), scopes=payload.scopes)
    db.add(row)
    write_audit(db, organization_id=principal.user.organization_id, actor_user_id=principal.user.id, action="api_key_created", entity_type="api_key", entity_id=str(row.id), after={"name": payload.name, "prefix": raw[:10]})
    db.commit()
    return {"id": str(row.id), "api_key": raw, "prefix": raw[:10]}


@router.get("/api-keys")
def list_keys(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.require("api_keys.manage")
    rows = db.scalars(select(ApiKey).where(ApiKey.organization_id == principal.user.organization_id)).all()
    return [{"id": str(row.id), "name": row.name, "prefix": row.prefix, "scopes": row.scopes, "revoked": row.revoked_at is not None} for row in rows]


@router.delete("/api-keys/{key_id}")
def revoke_key(key_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    principal.require("api_keys.manage")
    row = db.get(ApiKey, key_id)
    if row is None or row.organization_id != principal.user.organization_id:
        raise HTTPException(404, "API key not found")
    row.revoked_at = datetime.now(timezone.utc)
    write_audit(db, organization_id=principal.user.organization_id, actor_user_id=principal.user.id, action="api_key_revoked", entity_type="api_key", entity_id=str(row.id))
    db.commit()
    return {"ok": True}


@router.post("/webhooks/mt5/{token}")
async def mt5_webhook(token: str, request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    try:
        result = accept_webhook(
            db,
            token=token,
            api_key=request.headers.get("x-tradeguard-key", ""),
            timestamp=request.headers.get("x-tradeguard-timestamp", ""),
            nonce=request.headers.get("x-tradeguard-nonce", ""),
            signature=request.headers.get("x-tradeguard-signature", ""),
            body=body,
        )
        db.commit()
    except WebhookRejected as exc:
        db.rollback()
        if exc.status == 200:
            return {"duplicate": True}
        raise HTTPException(exc.status, exc.detail) from exc
    status = 200 if result.get("duplicate") else 202
    return Response(content=__import__("json").dumps(result), status_code=status, media_type="application/json")


def _account_or_404(db: Session, principal: Principal, account_id: UUID):
    try:
        return get_visible_account(db, principal.user, principal.roles, account_id)
    except AccountError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


def _rules_payload(db: Session, account) -> dict:
    from app.domain.ruleset import DEFAULT_RULES

    profile = db.scalar(select(RiskProfile).where(RiskProfile.account_id == account.id))
    rows = [] if profile is None else db.scalars(select(RiskRule).where(RiskRule.profile_id == profile.id)).all()
    by_code = {row.code: row for row in rows}
    payload: dict = {}
    enabled: dict[str, bool] = {}
    for code, field in RULE_FIELDS.items():
        row = by_code.get(code)
        if row is None:
            default = DEFAULT_RULES[code]
            payload[field] = default if isinstance(default, bool) else _plain(Decimal(default))
            enabled[field] = False
            continue
        payload[field] = row.bool_value if code == "ALLOW_TRADING" else (None if row.numeric_value is None else _plain(row.numeric_value))
        enabled[field] = bool(row.enabled)
    payload["enabled"] = enabled
    return payload


def _duration(open_time) -> str:
    if open_time is None:
        return ""
    from datetime import datetime, timezone

    seconds = int((datetime.now(timezone.utc) - open_time).total_seconds())
    hours, rem = divmod(max(seconds, 0), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m"


def _position_payload(row: Position) -> dict:
    return {
        "account_id": str(row.account_id),
        "ticket": row.ticket,
        "symbol": row.symbol,
        "direction": row.side,
        "lot": _plain(row.volume),
        "entry": _plain(row.entry_price),
        "current_price": _plain(row.current_price),
        "stop_loss": None if row.stop_loss is None else _plain(row.stop_loss),
        "take_profit": None if row.take_profit is None else _plain(row.take_profit),
        "floating_pl": _plain(row.profit, 2),
        "risk_amount": None if row.risk_amount is None else _plain(row.risk_amount, 2),
        "risk_percent": None if row.risk_percent is None else _plain(row.risk_percent, 2),
        "duration": _duration(row.open_time),
        "strategy": row.strategy or row.comment,
        "magic_number": row.magic_number,
    }


def _trade_payload(row: ClosedTrade) -> dict:
    return {
        "account_id": str(row.account_id),
        "ticket": row.ticket,
        "symbol": row.symbol,
        "direction": row.side,
        "lot": _plain(row.volume),
        "entry": _plain(row.entry_price),
        "close_price": _plain(row.close_price),
        "profit": _plain(row.profit, 2),
        "open_time": None if row.open_time is None else row.open_time.isoformat(),
        "close_time": None if row.close_time is None else row.close_time.isoformat(),
        "strategy": row.strategy or row.comment,
        "source": (row.strategy or row.comment or "").strip(),
        "magic_number": row.magic_number,
    }

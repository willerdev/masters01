from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, utcnow

JsonDoc = JSON


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    country: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(16), default="")
    phone_country_code: Mapped[str] = mapped_column(String(8), default="")
    phone_number: Mapped[str] = mapped_column(String(32), default="")
    admin_email: Mapped[str] = mapped_column(String(320), default="")
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_code: Mapped[str] = mapped_column(String(32), default="enterprise")
    join_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), index=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), index=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id"), index=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountRecovery(Base):
    __tablename__ = "account_recoveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    trc20_wallet: Mapped[str] = mapped_column(String(64))
    next_of_kin_name: Mapped[str] = mapped_column(String(200))
    second_next_of_kin_name: Mapped[str] = mapped_column(String(200))
    claim_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    claim_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class QualificationApplication(Base):
    __tablename__ = "qualification_applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    answers: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CapitalRequest(Base):
    __tablename__ = "capital_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    review_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MfaFactor(Base):
    __tablename__ = "user_mfa_factors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    factor_type: Mapped[str] = mapped_column(String(20), default="totp")
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("organization_id", "broker", "server", "account_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    broker: Mapped[str] = mapped_column(String(160), default="")
    server: Mapped[str] = mapped_column(String(160), default="")
    account_number: Mapped[str] = mapped_column(String(64))
    connection_method: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    leverage: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("100"))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_trading_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_blocks_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_token_hash: Mapped[str] = mapped_column(String(64), default="")
    control_state: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    trading_day_timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AccountGrant(Base):
    __tablename__ = "account_grants"
    __table_args__ = (UniqueConstraint("account_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)


class AccountCredential(Base):
    __tablename__ = "account_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), unique=True)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccountConnection(Base):
    __tablename__ = "account_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), unique=True)
    method: Mapped[str] = mapped_column(String(32))
    external_ref: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str] = mapped_column(String(80), default="")
    lag_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AccountState(Base):
    __tablename__ = "account_state"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    margin: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    free_margin: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    margin_level: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    day_start_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    trading_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "captured_at"), Index("ix_snapshots_account_time", "account_id", "captured_at"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    margin: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    free_margin: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    margin_level: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="live")


class SymbolSpecRow(Base):
    __tablename__ = "symbol_specs"
    __table_args__ = (UniqueConstraint("account_id", "broker_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    broker_symbol: Mapped[str] = mapped_column(String(64))
    canonical_symbol: Mapped[str] = mapped_column(String(64), default="")
    asset_class: Mapped[str] = mapped_column(String(32), default="forex")
    calc_mode: Mapped[str] = mapped_column(String(32), default="forex")
    digits: Mapped[int] = mapped_column(Integer, default=5)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    tick_value: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    contract_size: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    volume_min: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    volume_max: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    volume_step: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    profit_currency: Mapped[str] = mapped_column(String(8), default="USD")
    confidence: Mapped[str] = mapped_column(String(24), default="exact")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "ticket"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    ticket: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    current_price: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    profit: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    swap: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    commission: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    magic_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(String(200), default="")
    strategy: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TradeMilestone(Base):
    __tablename__ = "trade_milestones"
    __table_args__ = (UniqueConstraint("account_id", "ticket", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    ticket: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClosedTrade(Base):
    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("account_id", "ticket"), Index("ix_trades_account_close", "account_id", "close_time"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    ticket: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    profit: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    swap: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    commission: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    magic_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(String(200), default="")
    strategy: Mapped[str] = mapped_column(String(80), default="")


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("account_id", "ticket"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    ticket: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8), default="")
    order_type: Mapped[str] = mapped_column(String(32), default="")
    state: Mapped[str] = mapped_column(String(32), default="open")
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    __table_args__ = (Index("ix_quotes_account_symbol_time", "account_id", "symbol", "captured_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    bid: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    ask: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    spread: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("0"))
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="mt5")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskProfile(Base):
    __tablename__ = "risk_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RiskRule(Base):
    __tablename__ = "risk_rules"
    __table_args__ = (UniqueConstraint("profile_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_profiles.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    bool_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RiskDecisionRow(Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (Index("ix_decisions_account_time", "account_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    source_event_id: Mapped[str] = mapped_column(String(80), default="")
    decision: Mapped[str] = mapped_column(String(32), index=True)
    hits: Mapped[list] = mapped_column(JsonDoc, default=list)
    risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    open_risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    daily_loss_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    drawdown_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    stale_input: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RiskViolation(Base):
    __tablename__ = "risk_violations"
    __table_args__ = (Index("ix_violations_account_status", "account_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("risk_decisions.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    observed_value: Mapped[str] = mapped_column(String(80), default="")
    limit_value: Mapped[str] = mapped_column(String(80), default="")
    message: Mapped[str] = mapped_column(String(400), default="")
    status: Mapped[str] = mapped_column(String(24), default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OvertradingRow(Base):
    __tablename__ = "overtrading_assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    state: Mapped[str] = mapped_column(String(16))
    metrics: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    bands: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmergencyAction(Base):
    __tablename__ = "emergency_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    confirmation: Mapped[str] = mapped_column(String(80))
    result: Mapped[str] = mapped_column(String(40), default="accepted")
    detail: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrokerCommand(Base):
    __tablename__ = "broker_commands"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    command: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    detail: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_dedupe", "dedupe_key", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alerts.id"), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id"), index=True)
    channel: Mapped[str] = mapped_column(String(24))
    provider: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertChannelConfig(Base):
    __tablename__ = "alert_channel_configs"
    __table_args__ = (UniqueConstraint("organization_id", "channel"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    channel: Mapped[str] = mapped_column(String(24))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    destination: Mapped[str] = mapped_column(String(300), default="")
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), unique=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    api_key_hash: Mapped[str] = mapped_column(String(64))
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookInbox(Base):
    __tablename__ = "webhook_inbox"
    __table_args__ = (UniqueConstraint("endpoint_id", "external_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id"), index=True)
    external_event_id: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JsonDoc)
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    decision: Mapped[str] = mapped_column(String(32), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookNonce(Base):
    __tablename__ = "webhook_nonces"

    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JsonDoc, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_time", "organization_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(24), default="user")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    before: Mapped[dict | None] = mapped_column(JsonDoc, nullable=True)
    after: Mapped[dict | None] = mapped_column(JsonDoc, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    request_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramConfig(Base):
    __tablename__ = "telegram_configs"
    __table_args__ = (UniqueConstraint("organization_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PendingSignal(Base):
    __tablename__ = "pending_signals"
    __table_args__ = (UniqueConstraint("organization_id", "chat_id", "message_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    chat_id: Mapped[str] = mapped_column(String(32))
    chat_title: Mapped[str] = mapped_column(String(120), default="")
    message_id: Mapped[int] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    entry: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SetupWatch(Base):
    __tablename__ = "setup_watches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    chat_id: Mapped[str] = mapped_column(String(32), default="")
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    entry: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    take_profit: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    status: Mapped[str] = mapped_column(String(16), default="watching", index=True)
    order_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NakedLimit(Base):
    __tablename__ = "naked_limits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    ticket: Mapped[str] = mapped_column(String(64), default="")
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    entry: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    ignored_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    last_reminded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (UniqueConstraint("organization_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str] = mapped_column(String(80), default="")
    temperature: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.2"))
    max_tokens: Mapped[int] = mapped_column(Integer, default=800)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str] = mapped_column(String(300), default="")
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AiRequest(Base):
    __tablename__ = "ai_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(40), default="account_analysis")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), default="completed")
    context_hash: Mapped[str] = mapped_column(String(64), default="")
    response: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "captured_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))


class DrawdownSnapshot(Base):
    __tablename__ = "drawdown_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "captured_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    drawdown_abs: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))


class DailyStatistic(Base):
    __tablename__ = "daily_statistics"
    __table_args__ = (UniqueConstraint("account_id", "trading_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date)
    start_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    end_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)


class CopyLink(Base):
    __tablename__ = "copy_links"
    __table_args__ = (UniqueConstraint("master_account_id", "follower_account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    master_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    follower_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    volume_scale: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CopyDecision(Base):
    __tablename__ = "copy_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("copy_links.id"), index=True)
    master_ticket: Mapped[str] = mapped_column(String(64), default="")
    follower_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountGroup(Base):
    __tablename__ = "account_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountGroupMember(Base):
    __tablename__ = "account_group_members"
    __table_args__ = (UniqueConstraint("group_id", "account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account_groups.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (UniqueConstraint("organization_id", "name", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(32), default="1")
    description: Mapped[str] = mapped_column(String(500), default="")
    magic_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active")
    risk_limit_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1"))
    daily_loss_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("3"))
    max_positions: Mapped[int] = mapped_column(Integer, default=5)
    allowed_symbols: Mapped[list] = mapped_column(JsonDoc, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyAccount(Base):
    __tablename__ = "strategy_accounts"
    __table_args__ = (UniqueConstraint("strategy_id", "account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)


class TraderProfile(Base):
    __tablename__ = "trader_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="active")
    risk_per_trade_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0.5"))
    daily_loss_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.5"))
    max_positions: Mapped[int] = mapped_column(Integer, default=5)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=10)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("5"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TraderAccount(Base):
    __tablename__ = "trader_accounts"
    __table_args__ = (UniqueConstraint("trader_id", "account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trader_profiles.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)


class RiskBudget(Base):
    __tablename__ = "risk_budgets"
    __table_args__ = (UniqueConstraint("organization_id", "scope_type", "scope_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(24))
    scope_key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(160), default="")
    max_daily_risk_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    allocated_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    reserved_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Fund(Base):
    __tablename__ = "funds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    base_currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(24), default="open")
    management_fee_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    performance_fee_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    crystallization: Mapped[str] = mapped_column(String(16), default="quarterly")
    high_water_mark: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1"))
    units_outstanding: Mapped[Decimal] = mapped_column(Numeric(28, 8), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundBook(Base):
    __tablename__ = "fund_books"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))


class FundBookAccount(Base):
    __tablename__ = "fund_book_accounts"
    __table_args__ = (UniqueConstraint("book_id", "account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fund_books.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)


class Investor(Base):
    __tablename__ = "investors"
    __table_args__ = (UniqueConstraint("organization_id", "email"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvestorHolding(Base):
    __tablename__ = "investor_holdings"
    __table_args__ = (UniqueConstraint("fund_id", "investor_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    investor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investors.id"), index=True)
    units: Mapped[Decimal] = mapped_column(Numeric(28, 8), default=Decimal("0"))
    high_water_mark: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1"))
    capital_paid: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))


class CustodyWallet(Base):
    __tablename__ = "custody_wallets"
    __table_args__ = (UniqueConstraint("fund_id", "address"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    investor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investors.id"), nullable=True, index=True)
    owner: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WalletMovement(Base):
    __tablename__ = "wallet_movements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("custody_wallets.id"), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    note: Mapped[str] = mapped_column(String(240), default="")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssetTransfer(Base):
    __tablename__ = "asset_transfers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    address: Mapped[str] = mapped_column(String(180), default="")
    provider_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    order_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    invoice_url: Mapped[str] = mapped_column(String(500), default="")
    note: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CapitalMovement(Base):
    __tablename__ = "capital_movements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    holding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investor_holdings.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    units: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NavRecord(Base):
    __tablename__ = "nav_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    aum: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    units_outstanding: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    high_water_mark: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeeRecord(Base):
    __tablename__ = "fee_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    holding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investor_holdings.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    calculation: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionSample(Base):
    __tablename__ = "execution_samples"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    requested_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    executed_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    spread: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReconciliationEvent(Base):
    __tablename__ = "reconciliation_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundOrder(Base):
    __tablename__ = "fund_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    fund_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("funds.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="rejected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundAllocation(Base):
    __tablename__ = "fund_allocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fund_orders.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeskRule(Base):
    __tablename__ = "desk_rules"
    __table_args__ = (UniqueConstraint("organization_id", "name", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    fund_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("funds.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")
    metric: Mapped[str] = mapped_column(String(40))
    operator: Mapped[str] = mapped_column(String(8))
    threshold: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    action: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboundWebhook(Base):
    __tablename__ = "outbound_webhooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboundDelivery(Base):
    __tablename__ = "outbound_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    webhook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbound_webhooks.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(400), default="")
    payload: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentProviderConfig(Base):
    __tablename__ = "payment_provider_configs"
    __table_args__ = (UniqueConstraint("organization_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CryptoPayment(Base):
    __tablename__ = "crypto_payments"
    __table_args__ = (UniqueConstraint("organization_id", "order_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(32), default="deposit")
    description: Mapped[str] = mapped_column(String(240), default="")
    price_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price_currency: Mapped[str] = mapped_column(String(16))
    pay_currency: Mapped[str] = mapped_column(String(32), default="")
    pay_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    pay_address: Mapped[str] = mapped_column(String(180), default="")
    invoice_url: Mapped[str] = mapped_column(String(500), default="")
    provider_payment_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    provider_status: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TradingHalt(Base):
    __tablename__ = "trading_halts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(String(400), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    level: Mapped[str] = mapped_column(String(16), default="info")
    component: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(String(400), default="")
    context: Mapped[dict] = mapped_column(JsonDoc, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(AuditLog, "before_update", propagate=True)
def _audit_no_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise PermissionError("audit logs are immutable")


@event.listens_for(AuditLog, "before_delete", propagate=True)
def _audit_no_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise PermissionError("audit logs are immutable")

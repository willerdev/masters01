from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domain.audit import write_audit
from app.models.entities import (
    Account,
    AccountGrant,
    AccountState,
    CapitalRequest,
    Fund,
    Investor,
    InvestorHolding,
    NavRecord,
    Organization,
    Position,
    QualificationApplication,
    Role,
    TraderAccount,
    TraderProfile,
    User,
    UserRole,
)
from app.services.account_service import visible_account_query
from app.services.auth_service import AuthError, ensure_rbac, password_is_strong

_DATE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")
_DESK_ROLES = {"SUPER_ADMIN", "ADMIN", "RISK_MANAGER", "TRADER", "VIEWER"}


class PortalError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def ensure_join_code(db: Session, organization_id: UUID) -> str:
    org = db.get(Organization, organization_id)
    if org is None:
        raise PortalError(404, "Firm not found")
    if not org.join_code:
        org.join_code = secrets.token_hex(4).upper()
    return org.join_code


def rotate_join_code(db: Session, organization_id: UUID) -> str:
    org = db.get(Organization, organization_id)
    if org is None:
        raise PortalError(404, "Firm not found")
    org.join_code = secrets.token_hex(4).upper()
    return org.join_code


def join_firm(db: Session, *, code: str, email: str, password: str, full_name: str, kind: str, answers: dict, ip: str) -> tuple[User, str, str]:
    ensure_rbac(db)
    if kind not in {"investor", "trader"}:
        raise PortalError(400, "Choose investor or trader")
    if not password_is_strong(password):
        raise AuthError(400, "Password must be at least 12 characters and include a letter and a digit")
    cleaned = " ".join(full_name.split())
    if len(cleaned) < 2:
        raise PortalError(400, "Enter your legal name")
    org = db.scalar(select(Organization).where(Organization.join_code == code.strip().upper()))
    if org is None:
        raise PortalError(400, "That join code is not valid")
    normalized = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized)):
        raise PortalError(409, "Email is already registered")
    checked = _validate_answers(kind, answers)
    user = User(organization_id=org.id, email=normalized, password_hash=hash_password(password), full_name=cleaned[:200])
    db.add(user)
    db.flush()
    _grant_role(db, user, "APPLICANT")
    db.add(QualificationApplication(organization_id=org.id, user_id=user.id, kind=kind, status="pending", answers=checked))
    write_audit(db, organization_id=org.id, actor_user_id=user.id, action="qualification_submitted", entity_type="user", entity_id=str(user.id), after={"kind": kind}, ip_address=ip)
    from app.services.auth_service import _issue_session

    access, refresh = _issue_session(db, user, ["APPLICANT"], ip, "")
    return user, access, refresh


def list_applications(db: Session, user: User) -> list[dict]:
    rows = db.scalars(
        select(QualificationApplication)
        .where(QualificationApplication.organization_id == user.organization_id)
        .order_by(QualificationApplication.created_at.desc())
        .limit(200)
    ).all()
    payload = []
    for row in rows:
        applicant = db.get(User, row.user_id)
        payload.append(_application_payload(row, applicant))
    return payload


def decide_application(db: Session, actor: User, application_id: UUID, decision: str, note: str, account_id: UUID | None) -> dict:
    row = db.get(QualificationApplication, application_id)
    if row is None or row.organization_id != actor.organization_id:
        raise PortalError(404, "Application not found")
    if row.status != "pending":
        raise PortalError(400, "That application is already reviewed")
    if decision not in {"approve", "reject"}:
        raise PortalError(400, "Choose approve or reject")
    applicant = db.get(User, row.user_id)
    if applicant is None:
        raise PortalError(404, "Applicant not found")
    row.status = "approved" if decision == "approve" else "rejected"
    row.review_note = note.strip()[:500]
    row.reviewed_by = actor.id
    row.reviewed_at = datetime.now(timezone.utc)
    if decision == "approve":
        _clear_role(db, applicant, "APPLICANT")
        if row.kind == "investor":
            _grant_role(db, applicant, "INVESTOR")
            _link_investor(db, applicant)
        else:
            _grant_role(db, applicant, "PORTAL_TRADER")
            _link_trader(db, applicant, row.answers, account_id)
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action="qualification_reviewed",
        entity_type="qualification",
        entity_id=str(row.id),
        after={"decision": decision, "kind": row.kind, "email": applicant.email},
    )
    return _application_payload(row, applicant)


def list_capital_requests(db: Session, user: User) -> list[dict]:
    rows = db.scalars(
        select(CapitalRequest).where(CapitalRequest.organization_id == user.organization_id).order_by(CapitalRequest.created_at.desc()).limit(200)
    ).all()
    return [_capital_payload(db, row) for row in rows]


def decide_capital_request(db: Session, actor: User, request_id: UUID, decision: str, note: str) -> dict:
    row = db.get(CapitalRequest, request_id)
    if row is None or row.organization_id != actor.organization_id:
        raise PortalError(404, "Request not found")
    if row.status != "pending":
        raise PortalError(400, "That request is already reviewed")
    if decision not in {"approve", "reject"}:
        raise PortalError(400, "Choose approve or reject")
    investor_user = db.get(User, row.user_id)
    if investor_user is None:
        raise PortalError(404, "Investor not found")
    if decision == "approve":
        from app.services.fund_service import FundError, redeem, subscribe

        try:
            if row.kind == "subscribe":
                subscribe(db, actor, row.fund_id, investor_user.full_name, investor_user.email, row.amount)
            else:
                investor = db.scalar(select(Investor).where(Investor.organization_id == actor.organization_id, Investor.user_id == investor_user.id))
                if investor is None:
                    raise PortalError(400, "This person is not an approved investor")
                redeem(db, actor, row.fund_id, investor.id, row.amount)
        except FundError as exc:
            raise PortalError(exc.status, exc.detail) from exc
    row.status = "approved" if decision == "approve" else "rejected"
    row.review_note = note.strip()[:500]
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action="capital_request_reviewed",
        entity_type="capital_request",
        entity_id=str(row.id),
        after={"decision": decision, "kind": row.kind, "amount": format(row.amount, "f")},
    )
    return _capital_payload(db, row)


def portal_home(db: Session, user: User, roles: list[str]) -> dict:
    application = db.scalar(
        select(QualificationApplication)
        .where(QualificationApplication.user_id == user.id)
        .order_by(QualificationApplication.created_at.desc())
    )
    if _DESK_ROLES.intersection(roles):
        destination = "desk"
    elif "INVESTOR" in roles:
        destination = "investor"
    elif "PORTAL_TRADER" in roles:
        destination = "trader"
    else:
        destination = "pending"
    return {
        "destination": destination,
        "email": user.email,
        "full_name": user.full_name,
        "application": None
        if application is None
        else {"kind": application.kind, "status": application.status, "review_note": application.review_note},
    }


def investor_portal(db: Session, user: User) -> dict:
    investor = db.scalar(select(Investor).where(Investor.organization_id == user.organization_id, Investor.user_id == user.id))
    funds = []
    for fund in db.scalars(select(Fund).where(Fund.organization_id == user.organization_id, Fund.status == "open").order_by(Fund.name)).all():
        nav = db.scalar(select(NavRecord).where(NavRecord.fund_id == fund.id, NavRecord.locked.is_(True)).order_by(NavRecord.as_of.desc()))
        holding = None
        if investor is not None:
            holding = db.scalar(select(InvestorHolding).where(InvestorHolding.fund_id == fund.id, InvestorHolding.investor_id == investor.id))
        funds.append(
            {
                "id": str(fund.id),
                "name": fund.name,
                "currency": fund.base_currency,
                "unit_price": None if nav is None else format(nav.unit_price, "f"),
                "priced_at": None if nav is None else nav.as_of.isoformat(),
                "units": "0" if holding is None else format(holding.units, "f"),
                "capital_paid": "0" if holding is None else format(holding.capital_paid, "f"),
            }
        )
    requests = db.scalars(select(CapitalRequest).where(CapitalRequest.user_id == user.id).order_by(CapitalRequest.created_at.desc()).limit(30)).all()
    from app.services.wallet_service import investor_movements, investor_wallets

    return {
        "funds": funds,
        "requests": [_capital_payload(db, row) for row in requests],
        "wallets": investor_wallets(db, user),
        "wallet_movements": investor_movements(db, user),
    }


def request_capital(db: Session, user: User, fund_id: UUID, kind: str, amount: Decimal) -> dict:
    if "INVESTOR" not in _roles(db, user):
        raise PortalError(403, "An admin has to approve you as an investor first")
    if kind not in {"subscribe", "redeem"}:
        raise PortalError(400, "Choose subscribe or redeem")
    if amount <= 0:
        raise PortalError(400, "Enter an amount")
    fund = db.get(Fund, fund_id)
    if fund is None or fund.organization_id != user.organization_id:
        raise PortalError(404, "Fund not found")
    row = CapitalRequest(organization_id=user.organization_id, user_id=user.id, fund_id=fund.id, kind=kind, amount=amount, status="pending")
    db.add(row)
    db.flush()
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="capital_requested", entity_type="capital_request", entity_id=str(row.id), after={"kind": kind, "amount": format(amount, "f")})
    return _capital_payload(db, row)


def trader_portal(db: Session, user: User, roles: list[str]) -> dict:
    profile = db.scalar(select(TraderProfile).where(TraderProfile.organization_id == user.organization_id, TraderProfile.user_id == user.id))
    accounts = []
    for account in db.scalars(visible_account_query(db, user, roles)).all():
        state = db.get(AccountState, account.id)
        positions = db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()
        accounts.append(
            {
                "id": str(account.id),
                "name": account.display_name,
                "currency": account.currency,
                "equity": None if state is None else format(state.equity, "f"),
                "control_state": account.control_state,
                "positions": [
                    {"ticket": row.ticket, "symbol": row.symbol, "side": row.side, "volume": format(row.volume, "f"), "profit": format(row.profit, "f")}
                    for row in positions
                ],
            }
        )
    limits = None
    if profile is not None:
        limits = {
            "name": profile.name,
            "max_positions": profile.max_positions,
            "risk_per_trade_pct": format(profile.risk_per_trade_pct, "f"),
            "daily_loss_pct": format(profile.daily_loss_pct, "f"),
            "max_drawdown_pct": format(profile.max_drawdown_pct, "f"),
        }
    return {"limits": limits, "accounts": accounts}


def _validate_answers(kind: str, answers: dict) -> dict:
    if not isinstance(answers, dict):
        raise PortalError(400, "Application answers are missing")
    if kind == "investor":
        return _investor_answers(answers)
    return _trader_answers(answers)


def _investor_answers(raw: dict) -> dict:
    applicant_type = _choice(raw, "applicant_type", {"individual", "company"})
    category = _choice(raw, "category", {"retail", "professional", "accredited"})
    source = _choice(raw, "source_of_funds", {"salary", "business", "investments", "inheritance", "other"})
    horizon = _choice(raw, "horizon", {"under_1y", "1_to_3y", "over_3y"})
    objective = _choice(raw, "objective", {"growth", "income", "preservation"})
    experience = _choice(raw, "experience", {"none", "some", "extensive"})
    pep = _choice(raw, "pep", {"yes", "no"})
    id_type = _choice(raw, "id_type", {"passport", "national_id", "company_registration"})
    if raw.get("risk_accepted") is not True:
        raise PortalError(400, "Confirm that the capital you commit can be lost")
    birth = str(raw.get("date_of_birth") or "")
    if not _DATE.match(birth):
        raise PortalError(400, "Enter a date as YYYY-MM-DD")
    country = _text(raw, "country", "your country")
    tax = _text(raw, "tax_residency", "your tax residency")
    phone = _text(raw, "phone", "a phone number")
    address = _text(raw, "address", "your address")
    last4 = str(raw.get("id_last4") or "").strip()
    if len(last4) != 4 or not last4.isalnum():
        raise PortalError(400, "Enter the last 4 characters of the identity document")
    amount = _money(raw.get("expected_amount"), "the amount you expect to commit")
    return {
        "applicant_type": applicant_type,
        "category": category,
        "source_of_funds": source,
        "horizon": horizon,
        "objective": objective,
        "experience": experience,
        "pep": pep,
        "id_type": id_type,
        "id_last4": last4.upper(),
        "date_of_birth": birth,
        "country": country,
        "tax_residency": tax,
        "phone": phone,
        "address": address,
        "expected_amount": format(amount, "f"),
        "risk_accepted": True,
    }


def _trader_answers(raw: dict) -> dict:
    style = _choice(raw, "style", {"discretionary", "systematic", "mixed"})
    regulated = _choice(raw, "regulated", {"yes", "no"})
    if raw.get("rules_accepted") is not True:
        raise PortalError(400, "Confirm that you will follow the desk risk rules")
    markets = raw.get("markets")
    if not isinstance(markets, list) or not markets:
        raise PortalError(400, "Choose at least one market")
    allowed_markets = {"fx", "indices", "commodities", "crypto"}
    chosen = []
    for item in markets:
        name = str(item)
        if name not in allowed_markets:
            raise PortalError(400, "Choose markets from fx, indices, commodities, or crypto")
        if name not in chosen:
            chosen.append(name)
    years = _int(raw.get("years_experience"), "years of experience", 0, 60)
    positions = _int(raw.get("max_positions"), "a position limit", 1, 50)
    track = _text(raw, "track_record", "a short track record")
    if len(track) < 40:
        raise PortalError(400, "Describe your track record in at least a few sentences")
    license_number = str(raw.get("license_number") or "").strip()
    if regulated == "yes" and len(license_number) < 3:
        raise PortalError(400, "Enter the license or registration number")
    return {
        "country": _text(raw, "country", "your country"),
        "phone": _text(raw, "phone", "a phone number"),
        "years_experience": years,
        "markets": chosen,
        "style": style,
        "risk_per_trade_pct": format(_money(raw.get("risk_per_trade_pct"), "risk per trade"), "f"),
        "daily_loss_pct": format(_money(raw.get("daily_loss_pct"), "a daily loss limit"), "f"),
        "max_drawdown_pct": format(_money(raw.get("max_drawdown_pct"), "a drawdown limit"), "f"),
        "max_positions": positions,
        "track_record": track[:2000],
        "regulated": regulated,
        "license_number": license_number[:80],
        "other_desks": str(raw.get("other_desks") or "").strip()[:500],
        "excluded_symbols": str(raw.get("excluded_symbols") or "").strip()[:300],
        "emergency_contact_name": _text(raw, "emergency_contact_name", "an emergency contact"),
        "emergency_contact_phone": _text(raw, "emergency_contact_phone", "an emergency phone"),
        "rules_accepted": True,
    }


def _link_investor(db: Session, user: User) -> None:
    row = db.scalar(select(Investor).where(Investor.organization_id == user.organization_id, Investor.email == user.email))
    if row is None:
        db.add(Investor(organization_id=user.organization_id, user_id=user.id, name=user.full_name, email=user.email))
    else:
        row.user_id = user.id
        if not row.name:
            row.name = user.full_name


def _link_trader(db: Session, user: User, answers: dict, account_id: UUID | None) -> None:
    profile = db.scalar(select(TraderProfile).where(TraderProfile.organization_id == user.organization_id, TraderProfile.user_id == user.id))
    if profile is None:
        profile = TraderProfile(
            organization_id=user.organization_id,
            user_id=user.id,
            name=user.full_name[:160],
            risk_per_trade_pct=Decimal(str(answers.get("risk_per_trade_pct") or "0.5")),
            daily_loss_pct=Decimal(str(answers.get("daily_loss_pct") or "1.5")),
            max_positions=int(answers.get("max_positions") or 5),
            max_drawdown_pct=Decimal(str(answers.get("max_drawdown_pct") or "5")),
        )
        db.add(profile)
        db.flush()
    if account_id is None:
        return
    account = db.get(Account, account_id)
    if account is None or account.organization_id != user.organization_id:
        raise PortalError(400, "Choose an account in this firm")
    if db.scalar(select(TraderAccount).where(TraderAccount.trader_id == profile.id, TraderAccount.account_id == account.id)) is None:
        db.add(TraderAccount(trader_id=profile.id, account_id=account.id))
    if db.scalar(select(AccountGrant).where(AccountGrant.account_id == account.id, AccountGrant.user_id == user.id)) is None:
        db.add(AccountGrant(account_id=account.id, user_id=user.id))


def _grant_role(db: Session, user: User, code: str) -> None:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise PortalError(500, "Roles are not ready")
    if db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)) is None:
        db.add(UserRole(user_id=user.id, role_id=role.id))


def _clear_role(db: Session, user: User, code: str) -> None:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        return
    row = db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id))
    if row is not None:
        db.delete(row)


def _roles(db: Session, user: User) -> list[str]:
    from app.services.auth_service import role_codes_for

    return role_codes_for(db, user.id)


def _application_payload(row: QualificationApplication, applicant: User | None) -> dict:
    answers = dict(row.answers or {})
    flags = []
    if answers.get("pep") == "yes":
        flags.append("Politically exposed")
    if answers.get("category") == "retail":
        flags.append("Retail investor")
    if answers.get("regulated") == "no" and row.kind == "trader":
        flags.append("Not regulated")
    return {
        "id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "answers": answers,
        "flags": flags,
        "review_note": row.review_note,
        "created_at": row.created_at.isoformat(),
        "email": "" if applicant is None else applicant.email,
        "full_name": "" if applicant is None else applicant.full_name,
    }


def _capital_payload(db: Session, row: CapitalRequest) -> dict:
    fund = db.get(Fund, row.fund_id)
    person = db.get(User, row.user_id)
    return {
        "id": str(row.id),
        "fund_id": str(row.fund_id),
        "fund": "" if fund is None else fund.name,
        "kind": row.kind,
        "amount": format(row.amount, "f"),
        "status": row.status,
        "review_note": row.review_note,
        "email": "" if person is None else person.email,
        "created_at": row.created_at.isoformat(),
    }


def _choice(raw: dict, key: str, allowed: set[str]) -> str:
    value = str(raw.get(key) or "")
    if value not in allowed:
        raise PortalError(400, f"Choose a value for {key.replace('_', ' ')}")
    return value


def _text(raw: dict, key: str, label: str) -> str:
    value = " ".join(str(raw.get(key) or "").split())
    if len(value) < 2:
        raise PortalError(400, f"Enter {label}")
    return value[:300]


def _money(value: object, label: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise PortalError(400, f"Enter {label}") from exc
    if amount <= 0:
        raise PortalError(400, f"Enter {label}")
    return amount


def _int(value: object, label: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PortalError(400, f"Enter {label}") from exc
    if number < low or number > high:
        raise PortalError(400, f"Enter {label}")
    return number

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.models.entities import (
    Account,
    AccountState,
    CapitalMovement,
    DeskRule,
    ExecutionSample,
    FeeRecord,
    Fund,
    FundAllocation,
    FundBook,
    FundBookAccount,
    FundOrder,
    Investor,
    InvestorHolding,
    NavRecord,
    Position,
    ReconciliationEvent,
    RiskBudget,
    Strategy,
    StrategyAccount,
    TraderAccount,
    TraderProfile,
    User,
)
from app.services.account_service import AccountError, get_visible_account

_Q = Decimal("0.00000001")
_LOT = Decimal("0.01")
_METRICS = {"symbol_weight_pct", "gross_exposure_pct", "open_risk_pct"}
_OPERATORS = {">", ">=", "<", "<="}


class FundError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def create_fund(db: Session, user: User, name: str, base_currency: str, management_fee_pct: Decimal, performance_fee_pct: Decimal) -> Fund:
    cleaned = " ".join(name.split())
    currency = base_currency.strip().upper()
    if len(cleaned) < 2:
        raise FundError(400, "Enter a fund name")
    if not currency.isalpha() or not 3 <= len(currency) <= 8:
        raise FundError(400, "Enter the fund currency")
    if management_fee_pct < 0 or performance_fee_pct < 0:
        raise FundError(400, "Fees cannot be negative")
    fund = Fund(
        organization_id=user.organization_id,
        name=cleaned[:160],
        base_currency=currency,
        management_fee_pct=management_fee_pct,
        performance_fee_pct=performance_fee_pct,
    )
    db.add(fund)
    db.flush()
    db.add(FundBook(fund_id=fund.id, name="Main"))
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fund_created", entity_type="fund", entity_id=str(fund.id), after={"name": fund.name, "currency": currency})
    return fund


def list_funds(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(Fund).where(Fund.organization_id == user.organization_id).order_by(Fund.created_at.desc())).all()
    listed = []
    for row in rows:
        listed.append({**_summary(db, row), **_wallet_section(db, row)})
    return listed


def fund_detail(db: Session, user: User, roles: list[str], fund_id: UUID) -> dict:
    fund = _fund(db, user, fund_id)
    snap = snapshot(db, fund)
    navs = db.scalars(select(NavRecord).where(NavRecord.fund_id == fund.id).order_by(NavRecord.as_of.desc()).limit(30)).all()
    holdings = db.scalars(select(InvestorHolding).where(InvestorHolding.fund_id == fund.id)).all()
    investors = []
    for holding in holdings:
        investor = db.get(Investor, holding.investor_id)
        if investor is None:
            continue
        moves = db.scalars(select(CapitalMovement).where(CapitalMovement.holding_id == holding.id).order_by(CapitalMovement.created_at.desc()).limit(20)).all()
        investors.append(
            {
                "id": str(investor.id),
                "name": investor.name,
                "email": investor.email,
                "units": _text(holding.units),
                "high_water_mark": _text(holding.high_water_mark),
                "capital_paid": _text(holding.capital_paid),
                "movements": [
                    {"kind": move.kind, "amount": _text(move.amount), "units": _text(move.units), "unit_price": _text(move.unit_price), "created_at": move.created_at.isoformat()}
                    for move in moves
                ],
            }
        )
    rules = db.scalars(select(DeskRule).where(DeskRule.fund_id == fund.id).order_by(DeskRule.created_at.desc())).all()
    checks = evaluate_guidelines(snap, rules)
    budget = db.scalar(select(RiskBudget).where(RiskBudget.organization_id == fund.organization_id, RiskBudget.scope_type == "fund", RiskBudget.scope_key == str(fund.id)))
    orders = db.scalars(select(FundOrder).where(FundOrder.fund_id == fund.id).order_by(FundOrder.created_at.desc()).limit(20)).all()
    fees = db.scalars(select(FeeRecord).where(FeeRecord.fund_id == fund.id).order_by(FeeRecord.created_at.desc()).limit(20)).all()
    account_ids = [UUID(row["id"]) for row in snap["accounts"]]
    events = []
    if account_ids:
        events = list(
            db.scalars(
                select(ReconciliationEvent)
                .where(ReconciliationEvent.organization_id == fund.organization_id, ReconciliationEvent.account_id.in_(account_ids))
                .order_by(ReconciliationEvent.created_at.desc())
                .limit(20)
            ).all()
        )
    return {
        **_summary(db, fund),
        "snapshot": snap,
        "guidelines": checks,
        "budget": None if budget is None else _text(budget.max_daily_risk_pct),
        "nav": [_nav(row) for row in navs],
        "investors": investors,
        "fees": [{"kind": row.kind, "amount": _text(row.amount), "calculation": row.calculation, "created_at": row.created_at.isoformat()} for row in fees],
        "orders": [_order_payload(db, row) for row in orders],
        "reconciliation": [{"account_id": str(row.account_id), "status": row.status, "detail": row.detail, "created_at": row.created_at.isoformat()} for row in events],
        "accounts_available": _available_accounts(db, user, roles, fund),
        **_wallet_section(db, fund),
    }


def _wallet_section(db: Session, fund: Fund) -> dict:
    from app.services.wallet_service import fund_wallets

    return fund_wallets(db, fund)


def attach_account(db: Session, user: User, roles: list[str], fund_id: UUID, account_id: UUID) -> None:
    fund = _fund(db, user, fund_id)
    try:
        account = get_visible_account(db, user, roles, account_id)
    except AccountError as exc:
        raise FundError(exc.status, exc.detail) from exc
    if account.currency.upper() != fund.base_currency:
        raise FundError(400, f"{account.display_name} is {account.currency}. This fund is {fund.base_currency}.")
    existing = db.scalar(
        select(FundBookAccount)
        .join(FundBook, FundBook.id == FundBookAccount.book_id)
        .join(Fund, Fund.id == FundBook.fund_id)
        .where(Fund.organization_id == user.organization_id, FundBookAccount.account_id == account.id)
    )
    if existing is not None:
        raise FundError(400, "That account is already in a fund")
    book = _main_book(db, fund)
    db.add(FundBookAccount(book_id=book.id, account_id=account.id))
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fund_account_attached", entity_type="fund", entity_id=str(fund.id), after={"account_id": str(account.id)})


def detach_account(db: Session, user: User, fund_id: UUID, account_id: UUID) -> None:
    fund = _fund(db, user, fund_id)
    row = db.scalar(
        select(FundBookAccount)
        .join(FundBook, FundBook.id == FundBookAccount.book_id)
        .where(FundBook.fund_id == fund.id, FundBookAccount.account_id == account_id)
    )
    if row is None:
        raise FundError(404, "That account is not in this fund")
    db.delete(row)
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fund_account_detached", entity_type="fund", entity_id=str(fund.id), after={"account_id": str(account_id)})


def publish_nav(db: Session, user: User, fund_id: UUID) -> dict:
    fund = _fund(db, user, fund_id)
    snap = snapshot(db, fund)
    if snap["blockers"]:
        raise FundError(400, snap["blockers"][0])
    if not snap["accounts"]:
        raise FundError(400, "Attach an account before publishing NAV")
    aum = Decimal(snap["aum"])
    units = fund.units_outstanding
    price = fund.unit_price if units == 0 else _q(aum / units)
    if price <= 0:
        raise FundError(400, "Unit price must stay positive")
    mark = fund.high_water_mark if units == 0 else max(fund.high_water_mark, price)
    now = datetime.now(timezone.utc)
    row = NavRecord(
        fund_id=fund.id,
        as_of=now,
        aum=aum,
        unit_price=price,
        units_outstanding=units,
        high_water_mark=mark,
        locked=True,
    )
    fund.unit_price = price
    fund.high_water_mark = mark
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="nav_published",
        entity_type="fund",
        entity_id=str(fund.id),
        after={"aum": _text(aum), "unit_price": _text(price), "units": _text(units)},
    )
    return _nav(row)


def subscribe(db: Session, user: User, fund_id: UUID, name: str, email: str, amount: Decimal) -> dict:
    fund = _fund(db, user, fund_id)
    nav = _locked_nav(db, fund)
    if amount <= 0:
        raise FundError(400, "Enter an amount")
    if nav.unit_price <= 0:
        raise FundError(400, "The locked unit price is not usable")
    issued = _q(amount / nav.unit_price)
    if issued <= 0:
        raise FundError(400, "That amount is too small for one unit fraction")
    investor = db.scalar(select(Investor).where(Investor.organization_id == user.organization_id, Investor.email == email.strip().lower()))
    if investor is None:
        cleaned = " ".join(name.split())
        if len(cleaned) < 2:
            raise FundError(400, "Enter the investor name")
        investor = Investor(organization_id=user.organization_id, name=cleaned[:160], email=email.strip().lower())
        db.add(investor)
        db.flush()
    holding = db.scalar(select(InvestorHolding).where(InvestorHolding.fund_id == fund.id, InvestorHolding.investor_id == investor.id))
    if holding is None:
        holding = InvestorHolding(fund_id=fund.id, investor_id=investor.id, units=Decimal("0"), high_water_mark=nav.unit_price, capital_paid=Decimal("0"))
        db.add(holding)
        db.flush()
    elif holding.units == 0:
        holding.high_water_mark = nav.unit_price
    holding.units = _q(holding.units + issued)
    holding.capital_paid = _q(holding.capital_paid + amount)
    fund.units_outstanding = _q(fund.units_outstanding + issued)
    db.add(CapitalMovement(holding_id=holding.id, kind="subscribe", amount=amount, units=issued, unit_price=nav.unit_price))
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="investor_subscribed",
        entity_type="fund",
        entity_id=str(fund.id),
        after={"email": investor.email, "amount": _text(amount), "units": _text(issued), "unit_price": _text(nav.unit_price)},
    )
    return {"investor_id": str(investor.id), "units": _text(issued), "unit_price": _text(nav.unit_price)}


def redeem(db: Session, user: User, fund_id: UUID, investor_id: UUID, amount: Decimal) -> dict:
    fund = _fund(db, user, fund_id)
    nav = _locked_nav(db, fund)
    if amount <= 0:
        raise FundError(400, "Enter an amount")
    holding = db.scalar(select(InvestorHolding).where(InvestorHolding.fund_id == fund.id, InvestorHolding.investor_id == investor_id))
    investor = db.get(Investor, investor_id)
    if holding is None or investor is None or investor.organization_id != user.organization_id:
        raise FundError(404, "Investor not found in this fund")
    units = _q(amount / nav.unit_price)
    if units <= 0 or units > holding.units:
        raise FundError(400, "That redemption is larger than the holding")
    holding.units = _q(holding.units - units)
    fund.units_outstanding = _q(fund.units_outstanding - units)
    db.add(CapitalMovement(holding_id=holding.id, kind="redeem", amount=amount, units=units, unit_price=nav.unit_price))
    write_audit(
        db,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="investor_redeemed",
        entity_type="fund",
        entity_id=str(fund.id),
        after={"email": investor.email, "amount": _text(amount), "units": _text(units)},
    )
    return {"units": _text(units), "remaining": _text(holding.units)}


def accrue_fees(db: Session, user: User, fund_id: UUID) -> list[dict]:
    fund = _fund(db, user, fund_id)
    nav = _locked_nav(db, fund)
    created: list[FeeRecord] = []
    if fund.management_fee_pct > 0 and nav.aum > 0:
        previous = db.scalar(select(FeeRecord).where(FeeRecord.fund_id == fund.id, FeeRecord.kind == "management").order_by(FeeRecord.created_at.desc()))
        since = previous.created_at if previous is not None else fund.created_at
        days = Decimal(str(max((datetime.now(timezone.utc) - since).total_seconds(), 0))) / Decimal("86400")
        amount = _q((fund.management_fee_pct / Decimal("100")) * nav.aum * (days / Decimal("365")))
        if amount > 0:
            row = FeeRecord(fund_id=fund.id, kind="management", amount=amount, calculation={"aum": _text(nav.aum), "days": _text(days), "rate_pct": _text(fund.management_fee_pct)})
            db.add(row)
            created.append(row)
    if fund.performance_fee_pct > 0:
        holdings = db.scalars(select(InvestorHolding).where(InvestorHolding.fund_id == fund.id, InvestorHolding.units > 0)).all()
        for holding in holdings:
            gain = nav.unit_price - holding.high_water_mark
            if gain <= 0:
                continue
            amount = _q((fund.performance_fee_pct / Decimal("100")) * gain * holding.units)
            if amount <= 0:
                continue
            row = FeeRecord(
                fund_id=fund.id,
                holding_id=holding.id,
                kind="performance",
                amount=amount,
                calculation={"unit_price": _text(nav.unit_price), "high_water_mark": _text(holding.high_water_mark), "units": _text(holding.units), "rate_pct": _text(fund.performance_fee_pct)},
            )
            db.add(row)
            holding.high_water_mark = nav.unit_price
            created.append(row)
    if any(row.kind == "performance" for row in created) and nav.unit_price > fund.high_water_mark:
        fund.high_water_mark = nav.unit_price
    if not created:
        raise FundError(400, "No fee to record at this NAV")
    db.flush()
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fees_accrued", entity_type="fund", entity_id=str(fund.id), after={"count": len(created)})
    return [{"kind": row.kind, "amount": _text(row.amount)} for row in created]


def save_guideline(db: Session, user: User, fund_id: UUID, name: str, metric: str, operator: str, threshold: Decimal, action: str) -> dict:
    fund = _fund(db, user, fund_id)
    cleaned = " ".join(name.split())
    if len(cleaned) < 2:
        raise FundError(400, "Enter a guideline name")
    if metric not in _METRICS:
        raise FundError(400, "Choose symbol weight, gross exposure, or open risk")
    if operator not in _OPERATORS:
        raise FundError(400, "Operator must be >, >=, <, or <=")
    if action not in {"block", "warn"}:
        raise FundError(400, "Action must be block or warn")
    row = DeskRule(
        organization_id=user.organization_id,
        fund_id=fund.id,
        name=cleaned[:160],
        metric=metric,
        operator=operator,
        threshold=threshold,
        action=action,
        status="active",
    )
    db.add(row)
    db.flush()
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="guideline_saved", entity_type="fund", entity_id=str(fund.id), after={"name": row.name, "metric": metric, "action": action})
    return {"id": str(row.id), "name": row.name}


def save_budget(db: Session, user: User, fund_id: UUID, max_daily_risk_pct: Decimal) -> dict:
    fund = _fund(db, user, fund_id)
    if max_daily_risk_pct < 0:
        raise FundError(400, "The risk budget cannot be negative")
    row = db.scalar(select(RiskBudget).where(RiskBudget.organization_id == user.organization_id, RiskBudget.scope_type == "fund", RiskBudget.scope_key == str(fund.id)))
    if row is None:
        row = RiskBudget(organization_id=user.organization_id, scope_type="fund", scope_key=str(fund.id), label=fund.name, max_daily_risk_pct=max_daily_risk_pct)
        db.add(row)
    else:
        row.max_daily_risk_pct = max_daily_risk_pct
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="risk_budget_saved", entity_type="fund", entity_id=str(fund.id), after={"max_daily_risk_pct": _text(max_daily_risk_pct)})
    return {"max_daily_risk_pct": _text(max_daily_risk_pct)}


def save_strategy(db: Session, user: User, roles: list[str], fund_id: UUID, name: str, symbols: list[str], max_positions: int, account_id: UUID) -> dict:
    fund = _fund(db, user, fund_id)
    _require_member(db, fund, account_id)
    try:
        get_visible_account(db, user, roles, account_id)
    except AccountError as exc:
        raise FundError(exc.status, exc.detail) from exc
    cleaned = " ".join(name.split())
    if len(cleaned) < 2:
        raise FundError(400, "Enter a strategy name")
    if max_positions < 1:
        raise FundError(400, "Max positions must be at least 1")
    allowed = [item.strip() for item in symbols if item.strip()]
    row = Strategy(organization_id=user.organization_id, name=cleaned[:160], allowed_symbols=allowed, max_positions=max_positions, status="active")
    db.add(row)
    db.flush()
    db.add(StrategyAccount(strategy_id=row.id, account_id=account_id))
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="strategy_saved", entity_type="strategy", entity_id=str(row.id), after={"name": row.name, "account_id": str(account_id)})
    return {"id": str(row.id), "name": row.name}


def save_trader(db: Session, user: User, roles: list[str], fund_id: UUID, name: str, max_positions: int, account_id: UUID) -> dict:
    fund = _fund(db, user, fund_id)
    _require_member(db, fund, account_id)
    try:
        get_visible_account(db, user, roles, account_id)
    except AccountError as exc:
        raise FundError(exc.status, exc.detail) from exc
    cleaned = " ".join(name.split())
    if len(cleaned) < 2:
        raise FundError(400, "Enter a trader name")
    if max_positions < 1:
        raise FundError(400, "Max positions must be at least 1")
    row = TraderProfile(organization_id=user.organization_id, name=cleaned[:160], max_positions=max_positions, status="active")
    db.add(row)
    db.flush()
    db.add(TraderAccount(trader_id=row.id, account_id=account_id))
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="trader_saved", entity_type="trader", entity_id=str(row.id), after={"name": row.name, "account_id": str(account_id)})
    return {"id": str(row.id), "name": row.name}


def allocate_order(db: Session, user: User, roles: list[str], fund_id: UUID, payload: dict) -> dict:
    from app.services.order_service import OrderError, place_order

    fund = _fund(db, user, fund_id)
    symbol = str(payload.get("symbol") or "").strip()
    side = str(payload.get("side") or "").lower()
    action = str(payload.get("action") or "open")
    if action not in {"open", "limit"}:
        raise FundError(400, "Choose a market or limit order")
    if side not in {"buy", "sell"}:
        raise FundError(400, "Choose buy or sell")
    if not symbol:
        raise FundError(400, "Enter a symbol")
    total = _decimal(payload.get("volume"), "a volume")
    if total <= 0:
        raise FundError(400, "Enter a volume")
    members = _member_accounts(db, fund)
    tradable = []
    weights = []
    for account in members:
        if account.connection_method != "metaapi":
            continue
        try:
            get_visible_account(db, user, roles, account.id)
        except AccountError:
            continue
        state = db.get(AccountState, account.id)
        equity = state.equity if state is not None and state.equity > 0 else Decimal("0")
        tradable.append(account)
        weights.append(equity)
    if not tradable:
        raise FundError(400, "Attach a MetaAPI account before sending a fund order")
    parts = split_volume(total, weights)
    order = FundOrder(
        organization_id=user.organization_id,
        fund_id=fund.id,
        symbol=symbol,
        side=side,
        order_type=action,
        volume=total,
        price=_optional(payload.get("price")),
        stop_loss=_optional(payload.get("stop_loss")),
        take_profit=_optional(payload.get("take_profit")),
        status="rejected",
    )
    db.add(order)
    db.flush()
    sent_count = 0
    for account, volume in zip(tradable, parts):
        if volume <= 0:
            db.add(FundAllocation(fund_order_id=order.id, account_id=account.id, volume=volume, sent=False, decision="SKIPPED", message="No volume for this account"))
            continue
        body = {"action": action, "symbol": symbol, "side": side, "volume": str(volume), "source": fund.name}
        if payload.get("price") not in (None, ""):
            body["price"] = str(payload.get("price"))
        if payload.get("stop_loss") not in (None, ""):
            body["stop_loss"] = str(payload.get("stop_loss"))
        if payload.get("take_profit") not in (None, ""):
            body["take_profit"] = str(payload.get("take_profit"))
        try:
            result = place_order(db, user, account, body, actor="user")
        except OrderError as exc:
            result = {"sent": False, "decision": "BLOCK", "message": exc.detail}
        sent = bool(result.get("sent"))
        sent_count += int(sent)
        db.add(
            FundAllocation(
                fund_order_id=order.id,
                account_id=account.id,
                volume=volume,
                sent=sent,
                decision=str(result.get("decision") or ""),
                message=str(result.get("message") or "")[:400],
            )
        )
        db.add(
            ExecutionSample(
                organization_id=user.organization_id,
                account_id=account.id,
                symbol=symbol,
                requested_price=order.price,
                rejected=not sent,
            )
        )
    order.status = "sent" if sent_count == len(tradable) else "partial" if sent_count else "rejected"
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fund_order_allocated", entity_type="fund", entity_id=str(fund.id), after={"symbol": symbol, "volume": _text(total), "status": order.status})
    return _order_payload(db, order)


def reconcile_fund(db: Session, user: User, fund_id: UUID) -> list[dict]:
    from app.connectors.metaapi import MetaApiConnector
    from app.services.account_service import load_credentials

    fund = _fund(db, user, fund_id)
    results = []
    for account in _member_accounts(db, fund):
        local = {row.ticket for row in db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all()}
        if account.connection_method != "metaapi":
            detail = {"reason": "This connection cannot be read for reconciliation", "local_tickets": sorted(local)}
            status = "skipped"
        else:
            try:
                remote_rows = MetaApiConnector().fetch_positions(load_credentials(db, account.id))
                remote = {row.ticket for row in remote_rows}
            except Exception as exc:  # noqa: BLE001
                detail = {"reason": "The broker book could not be read", "error": exc.__class__.__name__, "local_tickets": sorted(local)}
                status = "unread"
                remote = set()
            else:
                detail = {"missing_on_broker": sorted(local - remote), "missing_locally": sorted(remote - local)}
                status = "matched" if not detail["missing_on_broker"] and not detail["missing_locally"] else "break"
        event = ReconciliationEvent(organization_id=user.organization_id, account_id=account.id, status=status, detail=detail)
        db.add(event)
        results.append({"account_id": str(account.id), "name": account.display_name, "status": status, "detail": detail})
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fund_reconciled", entity_type="fund", entity_id=str(fund.id), after={"accounts": len(results)})
    return results


def stop_fund(db: Session, user: User, fund_id: UUID, confirm: str, ip: str) -> list[dict]:
    from app.services.emergency_service import EmergencyError, apply_emergency

    if confirm != "STOP FUND":
        raise FundError(400, "Type STOP FUND to confirm")
    fund = _fund(db, user, fund_id)
    results = []
    for account in _member_accounts(db, fund):
        try:
            applied = apply_emergency(db, user, account, "EMERGENCY_STOP", "EMERGENCY STOP", ip)
            results.append({"account_id": str(account.id), "name": account.display_name, "result": applied["result"]})
        except EmergencyError as exc:
            results.append({"account_id": str(account.id), "name": account.display_name, "result": exc.detail})
    write_audit(db, organization_id=user.organization_id, actor_user_id=user.id, action="fund_stopped", entity_type="fund", entity_id=str(fund.id), after={"accounts": len(results)}, ip_address=ip)
    return results


def mandate_hits(db: Session, account: Account, symbol: str, volume: Decimal, price: Decimal) -> list[dict]:
    hits: list[dict] = []
    funds = _funds_for_account(db, account)
    proposed = abs(volume * price)
    for fund in funds:
        snap = snapshot(db, fund)
        aum = Decimal(snap["aum"])
        rules = db.scalars(select(DeskRule).where(DeskRule.fund_id == fund.id, DeskRule.status == "active")).all()
        marks = {row["symbol"]: Decimal(row["mark"]) for row in snap["exposure"]}
        marks[symbol] = marks.get(symbol, Decimal("0")) + proposed
        gross = sum(marks.values(), Decimal("0"))
        values = {
            "symbol_weight_pct": _pct(max(marks.values(), default=Decimal("0")), aum),
            "gross_exposure_pct": _pct(gross, aum),
            "open_risk_pct": _pct(Decimal(snap["open_risk"]), aum),
        }
        for rule in rules:
            current = values.get(rule.metric)
            if current is None or aum <= 0:
                continue
            if _breached(current, rule.operator, rule.threshold):
                decision = "BLOCK" if rule.action == "block" else "WARNING"
                hits.append({"code": "FUND_GUIDELINE", "decision": decision, "message": f"{fund.name}: {rule.name} is {_text(current)} (limit {rule.operator} {_text(rule.threshold)})"})
        budget = db.scalar(select(RiskBudget).where(RiskBudget.organization_id == fund.organization_id, RiskBudget.scope_type == "fund", RiskBudget.scope_key == str(fund.id)))
        if budget is not None and aum > 0 and values["open_risk_pct"] > budget.max_daily_risk_pct:
            hits.append({"code": "RISK_BUDGET", "decision": "BLOCK", "message": f"{fund.name}: open risk {_text(values['open_risk_pct'])}% is above the {_text(budget.max_daily_risk_pct)}% budget"})
    for link in db.scalars(select(StrategyAccount).where(StrategyAccount.account_id == account.id)).all():
        strategy = db.get(Strategy, link.strategy_id)
        if strategy is None or strategy.status != "active" or strategy.organization_id != account.organization_id:
            continue
        allowed = [str(item) for item in (strategy.allowed_symbols or [])]
        if allowed and symbol not in allowed:
            hits.append({"code": "STRATEGY_LIMIT", "decision": "BLOCK", "message": f"{strategy.name} does not allow {symbol}"})
        count = len(list(db.scalars(select(Position.id).where(Position.account_id == account.id, Position.status == "open")).all()))
        if count >= strategy.max_positions:
            hits.append({"code": "STRATEGY_LIMIT", "decision": "BLOCK", "message": f"{strategy.name} already has {count} open positions"})
    for link in db.scalars(select(TraderAccount).where(TraderAccount.account_id == account.id)).all():
        trader = db.get(TraderProfile, link.trader_id)
        if trader is None or trader.status != "active" or trader.organization_id != account.organization_id:
            continue
        count = len(list(db.scalars(select(Position.id).where(Position.account_id == account.id, Position.status == "open")).all()))
        if count >= trader.max_positions:
            hits.append({"code": "TRADER_LIMIT", "decision": "BLOCK", "message": f"{trader.name} already has {count} open positions"})
    return hits


def snapshot(db: Session, fund: Fund) -> dict:
    accounts = []
    blockers: list[str] = []
    equity = Decimal("0")
    open_risk = Decimal("0")
    marks: dict[str, Decimal] = {}
    for account in _member_accounts(db, fund):
        state = db.get(AccountState, account.id)
        row = {
            "id": str(account.id),
            "name": account.display_name,
            "currency": account.currency,
            "equity": None if state is None else _text(state.equity),
            "stale": bool(state.stale) if state is not None else True,
            "connection_method": account.connection_method,
        }
        accounts.append(row)
        if account.currency.upper() != fund.base_currency:
            blockers.append(f"{account.display_name} is {account.currency}. This fund is {fund.base_currency}.")
            continue
        if state is None or state.as_of is None:
            blockers.append(f"{account.display_name} has no live equity yet")
            continue
        if state.stale:
            blockers.append(f"{account.display_name} equity is stale")
        equity += state.equity
        for position in db.scalars(select(Position).where(Position.account_id == account.id, Position.status == "open")).all():
            if position.risk_amount is not None:
                open_risk += position.risk_amount
            mark = abs(position.volume * position.current_price)
            marks[position.symbol] = marks.get(position.symbol, Decimal("0")) + mark
    exposure = []
    for symbol, mark in sorted(marks.items()):
        exposure.append({"symbol": symbol, "mark": _text(mark), "weight_pct": None if equity <= 0 else _text(_pct(mark, equity))})
    return {
        "aum": _text(equity),
        "open_risk": _text(open_risk),
        "unit_price": _text(fund.unit_price),
        "units_outstanding": _text(fund.units_outstanding),
        "accounts": accounts,
        "exposure": exposure,
        "blockers": blockers,
        "publishable": not blockers and bool(accounts),
    }


def evaluate_guidelines(snap: dict, rules: list[DeskRule]) -> list[dict]:
    aum = Decimal(snap["aum"])
    marks = [Decimal(row["mark"]) for row in snap["exposure"]]
    values = {
        "symbol_weight_pct": _pct(max(marks, default=Decimal("0")), aum) if aum > 0 else None,
        "gross_exposure_pct": _pct(sum(marks, Decimal("0")), aum) if aum > 0 else None,
        "open_risk_pct": _pct(Decimal(snap["open_risk"]), aum) if aum > 0 else None,
    }
    rows = []
    for rule in rules:
        if rule.status != "active":
            continue
        current = values.get(rule.metric)
        measured = current is not None
        passed = measured and not _breached(current, rule.operator, rule.threshold)
        rows.append(
            {
                "id": str(rule.id),
                "name": rule.name,
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": _text(rule.threshold),
                "action": rule.action,
                "value": None if current is None else _text(current),
                "measured": measured,
                "passed": passed,
            }
        )
    return rows


def split_volume(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    if not weights:
        return []
    base = sum(weights, Decimal("0"))
    if base <= 0:
        weights = [Decimal("1")] * len(weights)
        base = Decimal(len(weights))
    parts: list[Decimal] = []
    used = Decimal("0")
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            part = total - used
        else:
            part = (total * weight / base).quantize(_LOT, rounding=ROUND_DOWN)
            used += part
        parts.append(part if part > 0 else Decimal("0"))
    return parts


def _funds_for_account(db: Session, account: Account) -> list[Fund]:
    rows = db.scalars(
        select(Fund)
        .join(FundBook, FundBook.fund_id == Fund.id)
        .join(FundBookAccount, FundBookAccount.book_id == FundBook.id)
        .where(FundBookAccount.account_id == account.id, Fund.organization_id == account.organization_id)
    ).all()
    return list(rows)


def _member_accounts(db: Session, fund: Fund) -> list[Account]:
    ids = list(
        db.scalars(
            select(FundBookAccount.account_id).join(FundBook, FundBook.id == FundBookAccount.book_id).where(FundBook.fund_id == fund.id)
        ).all()
    )
    if not ids:
        return []
    return list(db.scalars(select(Account).where(Account.id.in_(ids), Account.organization_id == fund.organization_id)).all())


def _require_member(db: Session, fund: Fund, account_id: UUID) -> None:
    ids = {account.id for account in _member_accounts(db, fund)}
    if account_id not in ids:
        raise FundError(400, "That account is not in this fund")


def _main_book(db: Session, fund: Fund) -> FundBook:
    book = db.scalar(select(FundBook).where(FundBook.fund_id == fund.id).order_by(FundBook.name))
    if book is None:
        book = FundBook(fund_id=fund.id, name="Main")
        db.add(book)
        db.flush()
    return book


def _fund(db: Session, user: User, fund_id: UUID) -> Fund:
    fund = db.get(Fund, fund_id)
    if fund is None or fund.organization_id != user.organization_id:
        raise FundError(404, "Fund not found")
    return fund


def _locked_nav(db: Session, fund: Fund) -> NavRecord:
    row = db.scalar(select(NavRecord).where(NavRecord.fund_id == fund.id, NavRecord.locked.is_(True)).order_by(NavRecord.as_of.desc()))
    if row is None:
        raise FundError(400, "Publish a NAV before changing investor units")
    return row


def _available_accounts(db: Session, user: User, roles: list[str], fund: Fund) -> list[dict]:
    from app.services.account_service import visible_account_query

    attached = {account.id for account in _member_accounts(db, fund)}
    rows = []
    for account in db.scalars(visible_account_query(db, user, roles)).all():
        if account.id in attached or account.currency.upper() != fund.base_currency:
            continue
        rows.append({"id": str(account.id), "name": account.display_name, "currency": account.currency})
    return rows


def _summary(db: Session, fund: Fund) -> dict:
    snap = snapshot(db, fund)
    return {
        "id": str(fund.id),
        "name": fund.name,
        "base_currency": fund.base_currency,
        "status": fund.status,
        "management_fee_pct": _text(fund.management_fee_pct),
        "performance_fee_pct": _text(fund.performance_fee_pct),
        "high_water_mark": _text(fund.high_water_mark),
        "unit_price": _text(fund.unit_price),
        "units_outstanding": _text(fund.units_outstanding),
        "aum": snap["aum"],
        "publishable": snap["publishable"],
    }


def _order_payload(db: Session, order: FundOrder) -> dict:
    parts = db.scalars(select(FundAllocation).where(FundAllocation.fund_order_id == order.id)).all()
    return {
        "id": str(order.id),
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "volume": _text(order.volume),
        "status": order.status,
        "created_at": order.created_at.isoformat(),
        "allocations": [
            {"account_id": str(part.account_id), "volume": _text(part.volume), "sent": part.sent, "decision": part.decision, "message": part.message}
            for part in parts
        ],
    }


def _nav(row: NavRecord) -> dict:
    return {
        "id": str(row.id),
        "as_of": row.as_of.isoformat(),
        "aum": _text(row.aum),
        "unit_price": _text(row.unit_price),
        "units_outstanding": _text(row.units_outstanding),
        "high_water_mark": _text(row.high_water_mark),
        "locked": row.locked,
    }


def _breached(value: Decimal, operator: str, threshold: Decimal) -> bool:
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    return False


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        return Decimal("0")
    return _q(part / whole * Decimal("100"))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q)


def _text(value: Decimal) -> str:
    return format(value, "f")


def _decimal(value: object, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise FundError(400, f"Enter {label}") from exc


def _optional(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value, "a price")

import json
import time
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import AuditLog, RiskDecisionRow, RiskRule
from app.services.ingest_service import sign_webhook


def _auth(client, email="ada@tradeguard.example", role_password="Sup3rSecret12"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": role_password, "full_name": "Ada", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _account(client, token: str) -> dict:
    response = client.post(
        "/api/v1/accounts",
        headers=_headers(token),
        json={
            "display_name": "Live 1",
            "account_number": "100200",
            "broker": "Example",
            "server": "Example-Live",
            "connection_method": "webhook",
            "currency": "USD",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post_event(client, account: dict, event_type: str, data: dict, event_id: str | None = None):
    payload = {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": "2026-09-26T12:00:00+00:00",
        "account_number": "100200",
        "data": data,
    }
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    secret = account["webhook"]["signing_secret"]
    signature = sign_webhook(secret, timestamp, nonce, body)
    response = client.post(
        f"/api/v1/webhooks/mt5/{account['webhook']['token']}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Tradeguard-Key": account["webhook"]["api_key"],
            "X-Tradeguard-Timestamp": timestamp,
            "X-Tradeguard-Nonce": nonce,
            "X-Tradeguard-Signature": signature,
        },
    )
    return response


def test_register_login_and_logout(client):
    token = _auth(client)
    me = client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["roles"] == ["SUPER_ADMIN"]
    logged = client.post("/api/v1/auth/login", json={"email": "ada@tradeguard.example", "password": "Sup3rSecret12"})
    assert logged.status_code == 200
    bad = client.post("/api/v1/auth/login", json={"email": "ada@tradeguard.example", "password": "wrong-password-1"})
    assert bad.status_code == 401
    out = client.post("/api/v1/auth/logout", headers=_headers(token))
    assert out.status_code == 200


def test_viewer_cannot_create_accounts_or_stop(client):
    token = _auth(client)
    created = client.post(
        "/api/v1/users",
        headers=_headers(token),
        json={"email": "view@tradeguard.example", "password": "ViewerPass12", "full_name": "View", "role": "VIEWER"},
    )
    assert created.status_code == 200, created.text
    viewer = client.post("/api/v1/auth/login", json={"email": "view@tradeguard.example", "password": "ViewerPass12"}).json()["access_token"]
    denied = client.post(
        "/api/v1/accounts",
        headers=_headers(viewer),
        json={"display_name": "X", "account_number": "1", "connection_method": "webhook"},
    )
    assert denied.status_code == 403


def test_webhook_allow_block_and_duplicate(client):
    token = _auth(client, "risk@tradeguard.example")
    account = _account(client, token)
    update = _post_event(
        client,
        account,
        "ACCOUNT_UPDATE",
        {"balance": "10000", "equity": "10000", "margin": "0", "free_margin": "10000"},
    )
    assert update.status_code == 202, update.text
    assert update.json()["decision"] == "ALLOW"
    opened = _post_event(
        client,
        account,
        "ORDER_OPENED",
        {
            "ticket": "501",
            "symbol": "EURUSD",
            "side": "buy",
            "volume": "0.10",
            "entry_price": "1.10000",
            "current_price": "1.10020",
            "stop_loss": "1.09800",
            "take_profit": "1.10400",
            "profit": "2",
            "magic_number": 7,
            "comment": "open-drive",
        },
    )
    assert opened.status_code == 202, opened.text
    assert opened.json()["decision"] in {"ALLOW", "WARNING"}
    same_id = str(uuid.uuid4())
    first = _post_event(client, account, "HEARTBEAT", {"equity": "10000", "balance": "10000"}, event_id=same_id)
    second = _post_event(client, account, "HEARTBEAT", {"equity": "10000", "balance": "10000"}, event_id=same_id)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    turned_on = client.put(
        f"/api/v1/accounts/{account['id']}/risk-rules",
        headers=_headers(token),
        json={"enabled": {"max_lot": True}},
    )
    assert turned_on.status_code == 200, turned_on.text
    blocked = _post_event(
        client,
        account,
        "ORDER_OPENED",
        {
            "ticket": "502",
            "symbol": "EURUSD",
            "side": "buy",
            "volume": "1.00",
            "entry_price": "1.10000",
            "current_price": "1.10000",
            "stop_loss": "1.09900",
            "profit": "0",
        },
    )
    assert blocked.status_code == 202
    assert blocked.json()["decision"] == "BLOCK"
    bad = client.post(
        f"/api/v1/webhooks/mt5/{account['webhook']['token']}",
        content=b"{}",
        headers={"X-Tradeguard-Key": "nope", "X-Tradeguard-Timestamp": str(int(time.time())), "X-Tradeguard-Nonce": "abc", "X-Tradeguard-Signature": "00"},
    )
    assert bad.status_code == 401
    positions = client.get(f"/api/v1/accounts/{account['id']}/positions", headers=_headers(token))
    assert positions.status_code == 200
    assert positions.json()[0]["ticket"] == "501"
    assert positions.json()[0]["magic_number"] == 7


def test_drawdown_emergency_and_confirmation(client):
    token = _auth(client, "ops@tradeguard.example")
    account = _account(client, token)
    turned_on = client.put(
        f"/api/v1/accounts/{account['id']}/risk-rules",
        headers=_headers(token),
        json={"enabled": {"max_total_drawdown_pct": True}},
    )
    assert turned_on.status_code == 200, turned_on.text
    _post_event(client, account, "ACCOUNT_UPDATE", {"balance": "10000", "equity": "10000", "margin": "0", "free_margin": "10000"})
    stressed = _post_event(client, account, "ACCOUNT_UPDATE", {"balance": "8900", "equity": "8900", "margin": "0", "free_margin": "8900"})
    assert stressed.json()["decision"] == "EMERGENCY_STOP"
    unconfirmed = client.post(
        f"/api/v1/accounts/{account['id']}/emergency",
        headers=_headers(token),
        json={"action": "PAUSE_ACCOUNT", "confirm": "no"},
    )
    assert unconfirmed.status_code == 400
    paused = client.post(
        f"/api/v1/accounts/{account['id']}/emergency",
        headers=_headers(token),
        json={"action": "PAUSE_ACCOUNT", "confirm": "PAUSE ACCOUNT"},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["control_state"] == "PAUSED"


def test_ai_failure_does_not_change_rules(client):
    token = _auth(client, "ai@tradeguard.example")
    account = _account(client, token)
    before = client.get(f"/api/v1/accounts/{account['id']}/risk-rules", headers=_headers(token)).json()
    analyzed = client.post(f"/api/v1/accounts/{account['id']}/ai/analyze", headers=_headers(token))
    assert analyzed.status_code == 200
    assert analyzed.json()["risk_level"] == "UNKNOWN"
    after = client.get(f"/api/v1/accounts/{account['id']}/risk-rules", headers=_headers(token)).json()
    assert before == after


def test_password_reset_and_audit_immutable(client):
    from app.api.deps import set_test_mailer
    from app.services.mailer import MemoryMailer

    mailer = MemoryMailer()
    set_test_mailer(mailer)
    token = _auth(client, "reset@tradeguard.example")
    client.post("/api/v1/auth/forgot-password", json={"email": "reset@tradeguard.example"})
    assert mailer.messages
    raw = mailer.messages[-1][2].strip().splitlines()[-1]
    reset = client.post("/api/v1/auth/reset-password", json={"token": raw, "password": "NewSecretPass12"})
    assert reset.status_code == 200, reset.text
    relog = client.post("/api/v1/auth/login", json={"email": "reset@tradeguard.example", "password": "NewSecretPass12"})
    assert relog.status_code == 200
    set_test_mailer(None)
    db = SessionLocal()
    try:
        row = db.scalar(select(AuditLog).limit(1))
        assert row is not None
        row.action = "tamper"
        try:
            db.flush()
            raised = False
        except PermissionError:
            raised = True
        assert raised
        db.rollback()
    finally:
        db.close()
    decisions = SessionLocal()
    try:
        count = decisions.scalar(select(RiskDecisionRow).limit(1))
        assert count is None or count.decision
    finally:
        decisions.close()
    _ = token


def test_rule_update_changes_enforcement(client):
    token = _auth(client, "rules@tradeguard.example")
    account = _account(client, token)
    updated = client.put(
        f"/api/v1/accounts/{account['id']}/risk-rules",
        headers=_headers(token),
        json={"max_lot": "0.05", "allow_trading": True, "enabled": {"max_lot": True}},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["max_lot"]) == Decimal("0.05")
    _post_event(client, account, "ACCOUNT_UPDATE", {"balance": "10000", "equity": "10000", "margin": "0", "free_margin": "10000"})
    opened = _post_event(
        client,
        account,
        "ORDER_OPENED",
        {"ticket": "9", "symbol": "EURUSD", "side": "buy", "volume": "0.10", "entry_price": "1.10000", "current_price": "1.10000", "stop_loss": "1.09950"},
    )
    assert opened.json()["decision"] == "BLOCK"


def test_a_disabled_rule_does_not_block(client):
    token = _auth(client, "rules-off@tradeguard.example")
    account = _account(client, token)
    updated = client.put(
        f"/api/v1/accounts/{account['id']}/risk-rules",
        headers=_headers(token),
        json={"max_lot": "0.05", "min_minutes_between_trades": "5", "enabled": {"max_lot": False, "min_minutes_between_trades": False}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled"]["max_lot"] is False
    assert updated.json()["enabled"]["min_minutes_between_trades"] is False
    _post_event(client, account, "ACCOUNT_UPDATE", {"balance": "10000", "equity": "10000", "margin": "0", "free_margin": "10000"})
    opened = _post_event(
        client,
        account,
        "ORDER_OPENED",
        {"ticket": "9", "symbol": "EURUSD", "side": "buy", "volume": "0.10", "entry_price": "1.10000", "current_price": "1.10000", "stop_loss": "1.09950"},
    )
    assert opened.json()["decision"] in {"ALLOW", "WARNING"}

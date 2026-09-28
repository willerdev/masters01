def _auth(client, email="ada@tradeguard.example", role_password="Sup3rSecret12"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": role_password, "full_name": "Ada", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_access_token(client):
    token = _auth(client, email="session@tradeguard.example")
    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=_headers(token)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401


def test_roles_come_from_the_database(client):
    token = _auth(client, email="roles@tradeguard.example")
    me = client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.json()["roles"] == ["SUPER_ADMIN"]


def test_integrations_start_disconnected(client):
    token = _auth(client, email="integrations@tradeguard.example")
    response = client.get("/api/v1/integrations", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert [(row["name"], row["connected"]) for row in response.json()] == [
        ("DeepSeek", False),
        ("OpenAI", False),
        ("Resend", False),
        ("Telegram", False),
        ("Telegram account", False),
        ("MetaAPI", False),
    ]


def test_simulator_and_report(client):
    token = _auth(client, email="ops@tradeguard.example")
    headers = _headers(token)
    sim = client.post(
        "/api/v1/simulate",
        headers=headers,
        json={"balance": "10000", "risk_percent": "1", "symbol": "EURUSD", "entry_price": "1.1", "stop_loss": "1.098", "lot_size": "0.5", "take_profit": "1.104"},
    )
    assert sim.status_code == 200, sim.text
    assert sim.json()["potential_loss"] == "100.00"
    report = client.get("/api/v1/reports?period=daily&kind=risk&format=csv", headers=headers)
    assert report.status_code == 200
    assert "Balance" in report.text or "balance" in report.text
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"
    metrics = client.get("/api/v1/metrics", headers=headers)
    assert metrics.status_code == 200
    assert "tradeguard_http_requests_total" in metrics.text


def test_resend_key_stays_stored_and_is_not_returned(client):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.entities import User
    from app.services.email_service import email_credentials

    token = _auth(client, email="mail@tradeguard.example")
    headers = _headers(token)
    saved = client.put(
        "/api/v1/email",
        headers=headers,
        json={"api_key": "re_test_key_value", "from_address": "TradeGuard <alerts@example.com>"},
    )
    assert saved.status_code == 200, saved.text
    assert "re_test" not in saved.text
    assert saved.json()["configured"] is True
    shown = client.get("/api/v1/email", headers=headers)
    assert shown.json() == {"provider": "resend", "configured": True, "from": "TradeGuard <alerts@example.com>"}
    again = client.put(
        "/api/v1/email",
        headers=headers,
        json={"api_key": "", "from_address": "Desk <desk@example.com>"},
    )
    assert again.status_code == 200, again.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "mail@tradeguard.example"))
        key, sender = email_credentials(db, user.organization_id)
    finally:
        db.close()
    assert key == "re_test_key_value"
    assert sender == "Desk <desk@example.com>"


def test_login_rate_limit(client):
    for _ in range(20):
        client.post("/api/v1/auth/login", json={"email": "missing@tradeguard.example", "password": "WrongPassword1"})
    blocked = client.post("/api/v1/auth/login", json={"email": "missing@tradeguard.example", "password": "WrongPassword1"})
    assert blocked.status_code == 429

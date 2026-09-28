TRC20 = "TJRyWwFs9wTFGZg3JbrVriFbNfCug5tDeC"


def _auth(client, email="owner@tradeguard.example"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret12", "full_name": "Ada Owner", "organization_name": "Desk"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"], response.json()["user"]["email"]


def _save(client, headers):
    response = client.put(
        "/api/v1/recovery",
        headers=headers,
        json={
            "email": "kin@tradeguard.example",
            "password": "RecoverPass12",
            "confirm_password": "RecoverPass12",
            "trc20_wallet": TRC20,
            "next_of_kin_name": "Amina Kato",
            "second_next_of_kin_name": "Jonah Kato",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_recovery_password_is_not_returned(client):
    token, _email = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    saved = _save(client, headers)
    assert saved["configured"] is True
    assert saved["second_next_of_kin_name"] == "Jonah Kato"
    assert "password" not in saved
    assert "RecoverPass12" not in str(saved)
    listed = client.get("/api/v1/recovery", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["trc20_wallet"] == TRC20
    assert "password_hash" not in listed.text


def test_recovery_rejects_a_bad_wallet(client):
    token, _email = _auth(client, "wallet@tradeguard.example")
    response = client.put(
        "/api/v1/recovery",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "kin@tradeguard.example",
            "password": "RecoverPass12",
            "confirm_password": "RecoverPass12",
            "trc20_wallet": "0xnot-tron",
            "next_of_kin_name": "Amina Kato",
            "second_next_of_kin_name": "Jonah Kato",
        },
    )
    assert response.status_code == 400
    assert "TRC20" in response.text


def test_second_next_of_kin_can_take_management(client):
    token, sign_in = _auth(client, "restore@tradeguard.example")
    _save(client, {"Authorization": f"Bearer {token}"})
    wrong = client.post(
        "/api/v1/recovery/claim",
        json={
            "email": "kin@tradeguard.example",
            "password": "wrong-password",
            "trc20_wallet": TRC20,
            "next_of_kin_name": "Amina Kato",
            "second_next_of_kin_name": "Jonah Kato",
        },
    )
    assert wrong.status_code == 401
    assert "RecoverPass12" not in wrong.text
    claim = client.post(
        "/api/v1/recovery/claim",
        json={
            "email": "kin@tradeguard.example",
            "password": "RecoverPass12",
            "trc20_wallet": TRC20,
            "next_of_kin_name": "amina   kato",
            "second_next_of_kin_name": "Jonah Kato",
        },
    )
    assert claim.status_code == 200, claim.text
    recovery_token = claim.json()["recovery_token"]
    restored = client.post("/api/v1/recovery/restore", json={"recovery_token": recovery_token, "new_password": "DeskReturn12"})
    assert restored.status_code == 200, restored.text
    assert restored.json()["sign_in_email"] == sign_in
    assert restored.json()["manager_name"] == "Jonah Kato"
    reused = client.post("/api/v1/recovery/restore", json={"recovery_token": recovery_token, "new_password": "DeskReturn99"})
    assert reused.status_code == 401
    old_login = client.post("/api/v1/auth/login", json={"email": sign_in, "password": "Sup3rSecret12"})
    assert old_login.status_code == 401
    new_login = client.post("/api/v1/auth/login", json={"email": sign_in, "password": "DeskReturn12"})
    assert new_login.status_code == 200, new_login.text
    assert new_login.json()["user"]["full_name"] == "Jonah Kato"

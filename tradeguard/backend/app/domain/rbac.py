ROLE_PERMISSIONS: dict[str, set[str]] = {
    "SUPER_ADMIN": {"*"},
    "ADMIN": {
        "users.manage",
        "accounts.read",
        "accounts.write",
        "accounts.connect",
        "risk_rules.read",
        "risk_rules.write",
        "emergency.pause",
        "emergency.stop",
        "emergency.close",
        "alerts.read",
        "alerts.manage",
        "audit.read",
        "ai.configure",
        "ai.invoke",
        "webhooks.manage",
        "api_keys.manage",
        "payments.manage",
        "funds.read",
        "funds.manage",
    },
    "RISK_MANAGER": {
        "accounts.read",
        "risk_rules.read",
        "risk_rules.write",
        "emergency.pause",
        "emergency.stop",
        "emergency.close",
        "alerts.read",
        "alerts.manage",
        "audit.read",
        "ai.invoke",
        "webhooks.manage",
        "funds.read",
        "funds.manage",
    },
    "TRADER": {
        "accounts.read",
        "accounts.write",
        "accounts.connect",
        "risk_rules.read",
        "risk_rules.write",
        "emergency.pause",
        "alerts.read",
        "ai.invoke",
        "webhooks.manage",
        "funds.read",
    },
    "VIEWER": {
        "accounts.read",
        "risk_rules.read",
        "alerts.read",
        "funds.read",
    },
    "APPLICANT": set(),
    "INVESTOR": {"portal.investor"},
    "PORTAL_TRADER": {"portal.trader", "accounts.read", "accounts.write"},
}

ALL_PERMISSIONS = sorted({code for codes in ROLE_PERMISSIONS.values() for code in codes if code != "*"})


def allows(role_codes: list[str], permission: str) -> bool:
    for role in role_codes:
        granted = ROLE_PERMISSIONS.get(role, set())
        if "*" in granted or permission in granted:
            return True
    return False

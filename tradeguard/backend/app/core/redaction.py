from __future__ import annotations

import logging

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "api_key",
    "apikey",
    "secret",
    "token",
    "bot_token",
    "trading_bot_token",
    "api_hash",
    "openai_api_key",
    "user_session",
    "phone_code_hash",
    "app_api_hash",
    "access_token",
    "refresh_token",
    "authorization",
    "ciphertext",
    "master_key",
    "smtp_password",
    "resend_api_key",
    "auth_token",
    "signing_secret",
    "ipn_secret",
    "merchant_id",
    "payout_password",
}


def redact(value: object) -> object:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS or lowered.endswith("_secret") or lowered.endswith("_password"):
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = redact(record.args)
        message = record.getMessage()
        lowered = message.lower()
        if any(key in lowered for key in ("password=", "authorization:", "bearer ", "api_key=")):
            record.msg = "[redacted log line]"
            record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(item, RedactFilter) for item in root.filters):
        root.addFilter(RedactFilter())

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class EncryptionError(Exception):
    pass


def _master_key() -> bytes:
    settings = get_settings()
    raw = settings.master_key.strip()
    if not raw:
        raise EncryptionError("MASTER_KEY is not configured")
    if settings.environment == "production" and raw == settings.local_dev_master_key:
        raise EncryptionError("Refusing the local development master key in production")
    try:
        key = base64.b64decode(raw)
    except Exception as exc:  # noqa: BLE001
        raise EncryptionError("MASTER_KEY must be base64") from exc
    if len(key) != 32:
        raise EncryptionError("MASTER_KEY must decode to 32 bytes")
    return key


def encrypt_json(payload: dict) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    token = AESGCM(_master_key()).encrypt(nonce, json.dumps(payload).encode("utf-8"), None)
    return nonce, token


def decrypt_json(nonce: bytes, ciphertext: bytes) -> dict:
    raw = AESGCM(_master_key()).decrypt(nonce, ciphertext, None)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise EncryptionError("credential payload must be an object")
    return data

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.strip().upper() + "=" * ((8 - len(secret.strip()) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def totp_at(secret: str, moment: int) -> str:
    counter = int(moment // 30)
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def verify_totp(secret: str, code: str, *, now: int | None = None, window: int = 1) -> bool:
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) != 6 or not secret:
        return False
    moment = int(time.time()) if now is None else now
    for skew in range(-window, window + 1):
        if hmac.compare_digest(totp_at(secret, moment + skew * 30), digits):
            return True
    return False


def otpauth_uri(email: str, secret: str) -> str:
    label = urllib.parse.quote(f"TradeGuard:{email}")
    issuer = urllib.parse.quote("TradeGuard")
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"

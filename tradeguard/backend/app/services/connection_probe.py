from __future__ import annotations

from app.connectors.local_mt5 import LocalMT5Connector
from app.connectors.metaapi import MetaApiConnector


def probe_connection(method: str, credentials: dict | None) -> dict:
    payload = credentials or {}
    if method == "metaapi":
        return MetaApiConnector().inspect(payload)
    if method == "local_mt5":
        return LocalMT5Connector().inspect(payload)
    return {
        "ok": False,
        "status": "unsupported",
        "error_code": "unsupported_method",
        "detail": "Choose MetaAPI or MetaTrader 5",
        "region": "",
        "account": None,
    }

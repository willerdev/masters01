from __future__ import annotations

import sys

from app.connectors.normalize import normalize_position
from app.connectors.types import CloseResult, ConnectionTest, ConnectorCapabilities, NormalizedPosition


class LocalMT5Connector:
    """Windows terminal adapter.

    The MetaTrader5 package imports only inside a logged-in Windows terminal
    session. On any other host this connector reports that the edge agent is
    required and still accepts normalized events through the ingest API.
    """

    name = "local_mt5"

    def capabilities(self) -> ConnectorCapabilities:
        available = sys.platform.startswith("win")
        return ConnectorCapabilities(available, available, available, "local_mt5")

    def inspect(self, credentials: dict) -> dict:
        if not sys.platform.startswith("win"):
            return _fail(
                "agent_required",
                "windows_terminal_required",
                "MetaTrader 5 must be running and logged in on this computer. This machine cannot attach to the terminal.",
            )
        login = str(credentials.get("login") or "").strip()
        password = str(credentials.get("password") or "")
        server = str(credentials.get("server") or "").strip()
        if not login.isdigit() or not password or not server:
            return _fail("missing_credentials", "credentials_missing", "Enter the MT5 login, password, and server")
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return _fail("package_missing", "metatrader5_not_installed", "The MetaTrader5 package is not installed on this computer")
        if not mt5.initialize(login=int(login), password=password, server=server):
            mt5.shutdown()
            return _fail("login_failed", "mt5_initialize_failed", "MetaTrader 5 did not accept the login. Keep the terminal running on this computer.")
        info = mt5.account_info()
        mt5.shutdown()
        if info is None:
            return _fail("no_account", "mt5_account_info_empty", "The terminal returned no account")
        number = str(getattr(info, "login", login))
        name = str(getattr(info, "name", "") or number)
        return {
            "ok": True,
            "status": "connected",
            "error_code": "",
            "detail": "",
            "region": "",
            "account": {
                "display_name": name,
                "account_number": number,
                "broker": str(getattr(info, "company", "") or ""),
                "server": str(getattr(info, "server", server) or server),
                "currency": str(getattr(info, "currency", "USD") or "USD").upper(),
                "leverage": str(getattr(info, "leverage", "100")),
                "balance": str(getattr(info, "balance", "0")),
                "equity": str(getattr(info, "equity", "0")),
                "margin": str(getattr(info, "margin", "0")),
                "free_margin": str(getattr(info, "margin_free", "0")),
                "margin_level": None if getattr(info, "margin_level", None) in (None, "") else str(info.margin_level),
            },
        }

    def test_connection(self, credentials: dict) -> ConnectionTest:
        result = self.inspect(credentials)
        return ConnectionTest(result["ok"], result["status"], result["error_code"], result["detail"])

    def fetch_positions(self, credentials: dict) -> list[NormalizedPosition]:
        if not sys.platform.startswith("win"):
            raise RuntimeError("MetaTrader 5 must be running on this computer to read open trades")
        login = str(credentials.get("login") or "").strip()
        password = str(credentials.get("password") or "")
        server = str(credentials.get("server") or "").strip()
        if not login.isdigit() or not password or not server:
            raise RuntimeError("MetaTrader 5 needs login, password, and server")
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:
            raise RuntimeError("The MetaTrader5 package is not installed on this computer") from exc
        if not mt5.initialize(login=int(login), password=password, server=server):
            mt5.shutdown()
            raise RuntimeError("MetaTrader 5 did not accept the login")
        try:
            rows = mt5.positions_get() or []
            positions = []
            for row in rows:
                positions.append(
                    normalize_position(
                        {
                            "ticket": getattr(row, "ticket", ""),
                            "symbol": getattr(row, "symbol", ""),
                            "side": "buy" if getattr(row, "type", 1) == 0 else "sell",
                            "volume": getattr(row, "volume", 0),
                            "entry_price": getattr(row, "price_open", 0),
                            "current_price": getattr(row, "price_current", 0),
                            "stop_loss": getattr(row, "sl", None),
                            "take_profit": getattr(row, "tp", None),
                            "profit": getattr(row, "profit", 0),
                            "swap": getattr(row, "swap", 0),
                            "magic_number": getattr(row, "magic", 0),
                            "comment": getattr(row, "comment", ""),
                        }
                    )
                )
            return positions
        finally:
            mt5.shutdown()

    def close_all(self, credentials: dict) -> CloseResult:
        if not self.capabilities().can_close:
            return CloseResult(False, "command_queue", error_code="windows_terminal_required")
        return CloseResult(False, "local_mt5", error_code="close_via_agent")


def _fail(status: str, error_code: str, detail: str) -> dict:
    return {"ok": False, "status": status, "error_code": error_code, "detail": detail, "region": "", "account": None}

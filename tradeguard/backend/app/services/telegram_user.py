"""Read Telegram chats with the user's own login and copy new messages to DeepSeek."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.services.alert_service import TelegramError, _BOT_TOKEN, _telegram_secret, _write_telegram_secret

logger = logging.getLogger(__name__)

_PHONE = re.compile(r"\+\d{8,15}")
_CODE = re.compile(r"\d{4,8}")
_CHAT_ID = re.compile(r"-?\d{1,20}")
_MAX_CHATS = 30
_FETCH_LIMIT = 5
_TRADE_LIMIT = 3
_PENDING_TTL = timedelta(minutes=10)


class TelegramSessionError(Exception):
    pass


class TelegramFloodError(Exception):
    pass


class CopiedMessage:
    def __init__(
        self,
        chat_id: str,
        title: str,
        message_id: int,
        text: str,
        image: bytes | None = None,
        mime: str = "image/jpeg",
    ) -> None:
        self.chat_id = str(chat_id)
        self.title = title
        self.message_id = int(message_id)
        self.text = text
        self.image = image
        self.mime = mime


def request_login_code(db: Session, organization_id: UUID, phone: str) -> dict:
    saved = _credentials(db, organization_id)
    phone = re.sub(r"[\s()-]", "", phone.strip())
    if not _PHONE.fullmatch(phone):
        raise TelegramError(400, "Enter the phone number with the country code, starting with +")
    if saved.get("user_session") and saved.get("user_connected"):
        raise TelegramError(400, "Telegram account is already connected. Disconnect it before signing in again.")

    async def worker(client):
        from telethon.errors import ApiIdInvalidError, FloodWaitError, PhoneNumberInvalidError

        if await client.is_user_authorized():
            return {"already": True}
        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            raise TelegramError(400, "Enter the phone number with the country code, starting with +") from exc
        except ApiIdInvalidError as exc:
            raise TelegramError(400, "Save the App ID and App API hash from my.telegram.org") from exc
        except FloodWaitError as exc:
            raise TelegramFloodError from exc
        return {"hash": str(sent.phone_code_hash)}

    try:
        outcome, session = _attempt_connect(saved, worker)
    except TelegramFloodError as exc:
        raise TelegramError(429, "Telegram asked us to wait. Try again shortly.") from exc
    except TelegramSessionError as exc:
        raise TelegramError(400, "Telegram did not accept that login") from exc
    if not session:
        raise TelegramError(502, "Telegram did not accept that login")
    saved["user_session"] = session
    if outcome.get("already"):
        saved["user_connected"] = True
        saved.pop("phone", None)
        saved.pop("phone_code_hash", None)
        _write_telegram_secret(db, organization_id, saved)
        return {"sent": False, "connected": True}
    saved["phone"] = phone
    saved["phone_code_hash"] = outcome["hash"]
    saved["user_connected"] = False
    _write_telegram_secret(db, organization_id, saved)
    return {"sent": True, "connected": False}


def confirm_login(db: Session, organization_id: UUID, code: str, password: str) -> dict:
    saved = _credentials(db, organization_id)
    code = re.sub(r"\s", "", code.strip())
    if not _CODE.fullmatch(code):
        raise TelegramError(400, "Enter the login code")
    phone = str(saved.get("phone") or "")
    phone_code_hash = str(saved.get("phone_code_hash") or "")
    if not phone or not phone_code_hash or not saved.get("user_session"):
        raise TelegramError(400, "Send a login code first")
    password = password.strip()

    async def worker(client):
        from telethon.errors import FloodWaitError, PasswordHashInvalidError, PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError

        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                raise TelegramError(400, "Enter the Telegram cloud password")
            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError as exc:
                raise TelegramError(400, "That cloud password was not accepted") from exc
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
            raise TelegramError(400, "That code was not accepted. Send a new code.") from exc
        except FloodWaitError as exc:
            raise TelegramFloodError from exc
        if await client.get_me() is None:
            raise TelegramError(400, "Telegram did not accept that login")
        return True

    try:
        _, session = _connect(str(saved["app_id"]), str(saved["api_hash"]), str(saved.get("user_session") or ""), worker)
    except TelegramFloodError as exc:
        raise TelegramError(429, "Telegram asked us to wait. Try again shortly.") from exc
    except TelegramSessionError as exc:
        saved["user_connected"] = False
        _write_telegram_secret(db, organization_id, saved)
        raise TelegramError(400, "Sign in to Telegram again") from exc
    if not session:
        raise TelegramError(502, "Telegram did not accept that login")
    saved["user_session"] = session
    saved["user_connected"] = True
    saved.pop("phone", None)
    saved.pop("phone_code_hash", None)
    _write_telegram_secret(db, organization_id, saved)
    return {"connected": True}


def forget_user(db: Session, organization_id: UUID) -> dict:
    saved = _telegram_secret(db, organization_id)
    if not saved:
        return {"connected": False}
    for key in ("user_session", "copy_chats", "copy_cursors", "user_connected", "phone", "phone_code_hash"):
        saved.pop(key, None)
    _write_telegram_secret(db, organization_id, saved)
    return {"connected": False}


def list_chats(db: Session, organization_id: UUID) -> dict:
    saved = _credentials(db, organization_id)
    _require_session(saved)
    dialogs, _latest, session = _dialogs_or_reject(db, organization_id, saved)
    selected = {str(row.get("id")) for row in saved.get("copy_chats") or [] if isinstance(row, dict)}
    _remember_session(saved, session)
    _write_telegram_secret(db, organization_id, saved)
    return {"connected": True, "chats": [_public(row, row["id"] in selected) for row in dialogs]}


def save_copy_chats(db: Session, organization_id: UUID, chat_ids: list[str]) -> dict:
    saved = _credentials(db, organization_id)
    _require_session(saved)
    wanted: list[str] = []
    for raw in chat_ids:
        cid = str(raw).strip()
        if not _CHAT_ID.fullmatch(cid):
            raise TelegramError(400, "Choose a chat from the list")
        if cid not in wanted:
            wanted.append(cid)
    if len(wanted) > _MAX_CHATS:
        raise TelegramError(400, "Choose up to 30 chats")
    dialogs, latest, session = _dialogs_or_reject(db, organization_id, saved)
    by_id = {row["id"]: row for row in dialogs}
    if any(cid not in by_id for cid in wanted):
        raise TelegramError(400, "Choose a chat from the list")
    previous = {str(row.get("id")) for row in saved.get("copy_chats") or [] if isinstance(row, dict)}
    cursors = {str(key): int(value or 0) for key, value in (saved.get("copy_cursors") or {}).items()}
    chosen = []
    new_cursors: dict[str, int] = {}
    for cid in wanted:
        row = by_id[cid]
        chosen.append({"id": cid, "title": row["title"], "type": row["type"], "peer": row["peer"]})
        new_cursors[cid] = int(cursors[cid]) if cid in previous and cid in cursors else int(latest.get(cid) or 0)
    saved["copy_chats"] = chosen
    saved["copy_cursors"] = new_cursors
    _remember_session(saved, session)
    _write_telegram_secret(db, organization_id, saved)
    return {"chats": [_public(row, True) for row in chosen]}


def drain_copied_signals(db: Session) -> None:
    from app.models.entities import TelegramConfig

    expire_pending_signals(db)
    rows = db.scalars(select(TelegramConfig)).all()
    for row in rows:
        try:
            _drain_org(db, row.organization_id)
        except Exception:
            logger.warning("telegram_copy_failed")


def _drain_org(db: Session, organization_id: UUID) -> None:
    saved = _telegram_secret(db, organization_id)
    chats = [row for row in (saved.get("copy_chats") or []) if isinstance(row, dict)]
    token = str(saved.get("bot_token") or "")
    bot_chat = str(saved.get("chat_id") or "")
    if not saved.get("user_session") or not saved.get("user_connected") or not chats:
        return
    if not bot_chat or not _BOT_TOKEN.fullmatch(token):
        return
    try:
        incoming, session, connected = _fetch_updates(saved)
    except TelegramSessionError:
        saved["user_connected"] = False
        _write_telegram_secret(db, organization_id, saved)
        logger.warning("telegram_copy_session_rejected")
        return
    except TelegramFloodError:
        logger.warning("telegram_copy_flood")
        return
    selected = {str(row.get("id")): str(row.get("title") or "Telegram") for row in chats}
    cursors = {str(key): int(value or 0) for key, value in (saved.get("copy_cursors") or {}).items()}
    dirty = False
    if session and session != saved.get("user_session"):
        saved["user_session"] = session
        dirty = True
    if connected and not saved.get("user_connected"):
        saved["user_connected"] = True
        dirty = True
    traded = 0
    for item in incoming:
        cid = str(item.chat_id)
        if cid not in selected or cid == bot_chat:
            continue
        if item.message_id <= int(cursors.get(cid) or 0):
            continue
        if traded >= _TRADE_LIMIT:
            break
        body = _signal_text(db, organization_id, selected[cid], item)
        if not body:
            cursors[cid] = item.message_id
            dirty = True
            continue
        reply = _queue_signal(db, organization_id, selected[cid], cid, item.message_id, body, bool(saved.get("auto_execute")))
        if reply:
            try:
                _deliver(token, bot_chat, reply, [])
            except Exception:
                logger.warning("telegram_copy_reply_failed")
            traded += 1
        cursors[cid] = item.message_id
        dirty = True
    if dirty:
        saved["copy_cursors"] = cursors
        _write_telegram_secret(db, organization_id, saved)


def _fetch_updates(saved: dict) -> tuple[list[CopiedMessage], str, bool]:
    async def worker(client):
        return await _collect_messages(client, saved)

    incoming, session = _connect(str(saved.get("app_id") or ""), str(saved.get("api_hash") or ""), str(saved.get("user_session") or ""), worker)
    return incoming, session, True


def _signal_text(db: Session, organization_id: UUID, title: str, item: CopiedMessage) -> str:
    del title
    text = item.text.strip()
    note = ""
    if item.image:
        from app.services.ai_service import describe_image, openai_api_key

        key = openai_api_key(db, organization_id)
        if key:
            try:
                note = describe_image(key, item.image, item.mime or "image/jpeg", text).strip()
            except Exception:
                logger.warning("telegram_copy_image_failed")
                note = ""
    if note:
        return f"{text}\n\nImage: {note}".strip() if text else f"Image: {note}"
    return text


def _queue_signal(db: Session, organization_id: UUID, title: str, chat_id: str, message_id: int, text: str, auto_execute: bool) -> str:
    from app.connectors.synthetic_lots import minimum_lot
    from app.models.entities import PendingSignal
    from app.services.ai_service import extract_signal

    found = extract_signal(db, organization_id, text)
    if not found:
        return ""
    existing = db.scalar(
        select(PendingSignal).where(
            PendingSignal.organization_id == organization_id,
            PendingSignal.chat_id == chat_id,
            PendingSignal.message_id == message_id,
        )
    )
    if existing is not None:
        return ""
    row = PendingSignal(
        organization_id=organization_id,
        chat_id=chat_id,
        chat_title=title[:120],
        message_id=message_id,
        symbol=found["symbol"],
        side=found["side"],
        entry=found["entry"],
        stop_loss=found["stop_loss"],
        take_profit=found["take_profit"],
        volume=found["volume"] or minimum_lot(found["symbol"]) or Decimal("0.01"),
    )
    db.add(row)
    db.flush()
    if not auto_execute:
        return _pending_text(row)
    try:
        result = execute_pending_signal(db, organization_id, row.id)
    except TelegramError as exc:
        return exc.detail
    return str(result.get("message") or _pending_text(row))


def expire_pending_signals(db: Session, organization_id: UUID | None = None) -> None:
    from app.models.entities import PendingSignal

    cutoff = datetime.now(timezone.utc) - _PENDING_TTL
    stmt = delete(PendingSignal).where(PendingSignal.created_at < cutoff)
    if organization_id is not None:
        stmt = stmt.where(PendingSignal.organization_id == organization_id)
    db.execute(stmt)


def list_pending_signals(db: Session, organization_id: UUID) -> dict:
    from app.models.entities import PendingSignal

    expire_pending_signals(db, organization_id)
    rows = db.scalars(
        select(PendingSignal).where(PendingSignal.organization_id == organization_id).order_by(PendingSignal.created_at.desc())
    ).all()
    saved = _telegram_secret(db, organization_id)
    return {"auto_execute": bool(saved.get("auto_execute")), "signals": [_pending_public(row) for row in rows]}


def set_auto_execute(db: Session, organization_id: UUID, enabled: bool) -> dict:
    saved = _telegram_secret(db, organization_id)
    if not saved.get("bot_token"):
        raise TelegramError(400, "Save Telegram first")
    saved["auto_execute"] = bool(enabled)
    _write_telegram_secret(db, organization_id, saved)
    return {"auto_execute": bool(enabled)}


def execute_pending_signal(db: Session, organization_id: UUID, signal_id: UUID) -> dict:
    from app.models.entities import Account, PendingSignal, User
    from app.services.order_service import OrderError, place_order, trade_source

    expire_pending_signals(db, organization_id)
    row = db.scalar(select(PendingSignal).where(PendingSignal.organization_id == organization_id, PendingSignal.id == signal_id))
    if row is None:
        raise TelegramError(404, "That signal expired or was already executed")
    user = db.scalar(select(User).where(User.organization_id == organization_id, User.is_active.is_(True)).order_by(User.created_at))
    accounts = db.scalars(
        select(Account).where(Account.organization_id == organization_id, Account.connection_method == "metaapi", Account.ai_trading_enabled.is_(True))
    ).all()
    if user is None or not accounts:
        raise TelegramError(400, "Turn on Allow DeepSeek to trade on the account page, then execute the signal again.")
    if len(accounts) > 1:
        raise TelegramError(400, "Leave DeepSeek trading on for one account, then execute the signal again.")
    payload = {
        "action": "limit",
        "symbol": row.symbol,
        "side": row.side,
        "volume": row.volume,
        "price": row.entry,
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "source": trade_source(row.chat_title),
    }
    try:
        result = place_order(db, user, accounts[0], payload, actor="ai")
    except OrderError as exc:
        raise TelegramError(exc.status, exc.detail) from exc
    if not result.get("sent"):
        raise TelegramError(400, str(result.get("message") or "The trade was not sent"))
    message = f"Executed {row.side} {row.symbol} at {_plain_number(row.entry)} from {row.chat_title}."
    db.delete(row)
    return {"executed": True, "message": message}


def _pending_text(row) -> str:
    if row.stop_loss is None:
        stop = " No stop was given, so the stop will be 100 pips"
        take = " and the target 2R." if row.take_profit is None else f" and the target {_plain_number(row.take_profit)}."
    else:
        stop = f" stop {_plain_number(row.stop_loss)}"
        take = " target 2R." if row.take_profit is None else f" target {_plain_number(row.take_profit)}."
    return (
        f"Pending {row.side} {row.symbol} at {_plain_number(row.entry)} from {row.chat_title}. "
        f"Lot {_plain_number(row.volume)}.{stop}{take} Auto execute is off. It stays for 10 minutes."
    )


def _pending_public(row) -> dict:
    created = row.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    expires = None if created is None else created + _PENDING_TTL
    return {
        "id": str(row.id),
        "chat_title": row.chat_title,
        "symbol": row.symbol,
        "side": row.side,
        "entry": _plain_number(row.entry),
        "stop_loss": None if row.stop_loss is None else _plain_number(row.stop_loss),
        "take_profit": None if row.take_profit is None else _plain_number(row.take_profit),
        "volume": _plain_number(row.volume),
        "created_at": None if created is None else created.isoformat(),
        "expires_at": None if expires is None else expires.isoformat(),
    }


def _plain_number(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _deliver(token: str, chat_id: str, reply: str, images: list) -> None:
    from app.services.alert_service import _telegram, _telegram_photo

    _telegram(token, "sendMessage", {"chat_id": chat_id, "text": reply[:3900]})
    for image in images:
        if isinstance(image, bytes):
            _telegram_photo(token, chat_id, image, "OpenAI image")


def _attempt_connect(saved: dict, worker):
    app_id = str(saved["app_id"])
    api_hash = str(saved["api_hash"])
    try:
        return _connect(app_id, api_hash, str(saved.get("user_session") or ""), worker)
    except TelegramSessionError:
        return _connect(app_id, api_hash, "", worker)


def _dialogs_or_reject(db: Session, organization_id: UUID, saved: dict):
    try:
        return _load_dialogs(saved)
    except TelegramFloodError as exc:
        raise TelegramError(429, "Telegram asked us to wait. Try again shortly.") from exc
    except TelegramSessionError as exc:
        saved["user_connected"] = False
        _write_telegram_secret(db, organization_id, saved)
        raise TelegramError(400, "Sign in to Telegram again") from exc


def _load_dialogs(saved: dict):
    async def worker(client):
        return await _collect_dialogs(client)

    result, session = _connect(str(saved.get("app_id") or ""), str(saved.get("api_hash") or ""), str(saved.get("user_session") or ""), worker)
    dialogs, latest = result
    return dialogs, latest, session


def _connect(app_id: str, api_hash: str, session: str, worker):
    try:
        return asyncio.run(_open(app_id, api_hash, session, worker))
    except (TelegramSessionError, TelegramFloodError, TelegramError):
        raise
    except ValueError as exc:
        raise TelegramSessionError from exc
    except OSError as exc:
        raise TelegramError(502, "Telegram could not be reached") from exc
    except Exception as exc:
        if exc.__class__.__module__.startswith("telethon"):
            raise TelegramError(502, "Telegram could not be reached") from exc
        raise


async def _open(app_id: str, api_hash: str, session: str, worker):
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(session or None), int(app_id), api_hash)
    try:
        try:
            await client.connect()
        except Exception as exc:
            if _dead_session(exc):
                raise TelegramSessionError from exc
            raise
        try:
            result = await worker(client)
        except FloodWaitError as exc:
            raise TelegramFloodError from exc
        except Exception as exc:
            if _dead_session(exc):
                raise TelegramSessionError from exc
            raise
        return result, str(client.session.save() or "")
    finally:
        try:
            await client.disconnect()
        except Exception:
            logger.warning("telegram_user_disconnect_failed")


def _dead_session(exc: BaseException) -> bool:
    from telethon.errors import (
        AuthKeyInvalidError,
        AuthKeyUnregisteredError,
        SessionExpiredError,
        SessionRevokedError,
        UserDeactivatedBanError,
        UserDeactivatedError,
    )

    return isinstance(
        exc,
        (
            AuthKeyInvalidError,
            AuthKeyUnregisteredError,
            SessionExpiredError,
            SessionRevokedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ),
    )


async def _collect_dialogs(client) -> tuple[list[dict], dict[str, int]]:
    from telethon.tl.types import Channel, Chat, User
    from telethon.utils import get_peer_id

    dialogs = []
    latest: dict[str, int] = {}
    async for dialog in client.iter_dialogs(limit=100):
        entity = dialog.entity
        peer = _peer(entity, Channel, Chat, User)
        if peer is None:
            continue
        cid = str(get_peer_id(entity))
        kind = "private" if dialog.is_user else "group" if dialog.is_group else "channel"
        title = str(dialog.name or "Telegram").strip()[:120] or "Telegram"
        dialogs.append({"id": cid, "title": title, "type": kind, "peer": peer})
        message = dialog.message
        latest[cid] = int(message.id) if message is not None and getattr(message, "id", None) else 0
    return dialogs, latest


def _peer(entity, channel_type, chat_type, user_type) -> dict | None:
    if isinstance(entity, channel_type) and getattr(entity, "access_hash", None) is not None:
        return {"kind": "channel", "id": int(entity.id), "access_hash": int(entity.access_hash)}
    if isinstance(entity, chat_type):
        return {"kind": "chat", "id": int(entity.id)}
    if isinstance(entity, user_type) and getattr(entity, "access_hash", None) is not None:
        return {"kind": "user", "id": int(entity.id), "access_hash": int(entity.access_hash)}
    return None


async def _collect_messages(client, saved: dict) -> list[CopiedMessage]:
    from telethon.errors import FloodWaitError

    chats = [row for row in (saved.get("copy_chats") or []) if isinstance(row, dict)]
    cursors = saved.get("copy_cursors") or {}
    bot_chat = str(saved.get("chat_id") or "")
    found: list[CopiedMessage] = []
    for chat in chats:
        cid = str(chat.get("id") or "")
        if not cid or cid == bot_chat:
            continue
        peer = _input_peer(chat.get("peer"))
        if peer is None:
            continue
        cursor = int(cursors.get(cid) or 0)
        try:
            batch = []
            async for message in client.iter_messages(peer, min_id=cursor, reverse=True, limit=_FETCH_LIMIT):
                batch.append(message)
        except FloodWaitError as exc:
            raise TelegramFloodError from exc
        except Exception as exc:
            if _dead_session(exc):
                raise TelegramSessionError from exc
            logger.warning("telegram_copy_peer")
            continue
        title = str(chat.get("title") or "Telegram")
        for message in batch:
            copied = await _copied_message(client, cid, title, cursor, message)
            if copied is not None:
                found.append(copied)
    return found


async def _copied_message(client, chat_id: str, title: str, cursor: int, message) -> CopiedMessage | None:
    if message is None or not getattr(message, "id", None):
        return None
    message_id = int(message.id)
    if message_id <= cursor:
        return None
    if getattr(message, "action", None):
        return CopiedMessage(chat_id, title, message_id, "")
    text = str(getattr(message, "message", None) or "").strip()
    image = None
    if getattr(message, "photo", None):
        try:
            blob = await client.download_media(message, bytes)
        except Exception:
            blob = None
        if isinstance(blob, bytes) and 0 < len(blob) <= 8_000_000:
            image = blob
    return CopiedMessage(chat_id, title, message_id, text, image)


def _input_peer(peer):
    if not isinstance(peer, dict):
        return None
    try:
        raw_id = int(peer["id"])
    except (KeyError, TypeError, ValueError):
        return None
    from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser

    kind = str(peer.get("kind") or "")
    if kind == "channel":
        return InputPeerChannel(raw_id, int(peer.get("access_hash") or 0))
    if kind == "chat":
        return InputPeerChat(raw_id)
    if kind == "user":
        return InputPeerUser(raw_id, int(peer.get("access_hash") or 0))
    return None


def _credentials(db: Session, organization_id: UUID) -> dict:
    saved = _telegram_secret(db, organization_id)
    if not str(saved.get("app_id") or "").isdigit() or len(str(saved.get("api_hash") or "")) < 8:
        raise TelegramError(400, "Save the App ID and App API hash first")
    return saved


def _require_session(saved: dict) -> None:
    if not saved.get("user_session") or not saved.get("user_connected"):
        raise TelegramError(400, "Sign in to Telegram first")


def _remember_session(saved: dict, session: str) -> None:
    if session:
        saved["user_session"] = session
    saved["user_connected"] = True


def _public(row: dict, selected: bool) -> dict:
    return {
        "id": str(row["id"]),
        "title": str(row.get("title") or "Telegram"),
        "type": str(row.get("type") or "private"),
        "selected": selected,
    }

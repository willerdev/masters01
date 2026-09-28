from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.encryption import decrypt_json, encrypt_json
from app.core.resilience import CircuitBreaker, CircuitOpen
from app.models.entities import Alert, AlertChannelConfig, Notification, NotificationDelivery, TelegramConfig, User

logger = logging.getLogger(__name__)
_email_breaker = CircuitBreaker(fail_max=4, reset_seconds=60)
_hook_breaker = CircuitBreaker(fail_max=4, reset_seconds=60)
_telegram_breaker = CircuitBreaker(fail_max=4, reset_seconds=60)
_sms_breaker = CircuitBreaker(fail_max=4, reset_seconds=60)


_BOT_TOKEN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_HISTORY_LIMIT = 8
_HISTORY_TTL_SECONDS = 30 * 60


class TelegramError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def send_bot_test(token: str, paused_webhook: str = "") -> dict:
    token = token.strip()
    if not _BOT_TOKEN.fullmatch(token):
        raise TelegramError(400, "Enter the Telegram bot token from BotFather")
    me = _telegram(token, "getMe")
    if not me.get("ok"):
        raise TelegramError(400, "Telegram did not accept that bot token")
    username = str((me.get("result") or {}).get("username") or "")
    info = _telegram(token, "getWebhookInfo")
    active = str((info.get("result") or {}).get("url") or "") if info.get("ok") else ""
    remembered = active or paused_webhook
    if active:
        deleted = _telegram(token, "deleteWebhook", {"drop_pending_updates": False})
        if not deleted.get("ok"):
            raise TelegramError(400, "Telegram did not pause the existing webhook")
    updates = _telegram(token, "getUpdates", {"timeout": 0, "limit": 20})
    if not updates.get("ok"):
        raise TelegramError(400, _public_telegram_error(updates))
    chat_id = _latest_chat(updates.get("result") or [])
    if chat_id is None:
        where = f"@{username}" if username else "the bot"
        return {
            "sent": False,
            "bot": username,
            "chat_id": None,
            "paused_webhook": remembered,
            "detail": f"Send any message to {where}, then press Send test again.",
        }
    sent = _telegram(token, "sendMessage", {"chat_id": chat_id, "text": "TradeGuard test. This bot can reach you. Send a trade instruction in this chat."})
    if not sent.get("ok"):
        raise TelegramError(502, "Telegram did not deliver the test message")
    return {"sent": True, "bot": username, "chat_id": chat_id, "paused_webhook": "", "detail": ""}


def telegram_settings(db: Session, organization_id: UUID) -> dict:
    saved = _telegram_secret(db, organization_id)
    return {
        "app_id": str(saved.get("app_id") or ""),
        "api_hash_set": bool(saved.get("api_hash")),
        "bot_token_set": bool(saved.get("bot_token")),
        "account_connected": bool(saved.get("user_session")) and bool(saved.get("user_connected")),
        "auto_execute": bool(saved.get("auto_execute")),
    }


def save_telegram_settings(db: Session, organization_id: UUID, app_id: str, api_hash: str, bot_token: str) -> dict:
    current = _telegram_secret(db, organization_id)
    app_id = app_id.strip() or str(current.get("app_id") or "")
    api_hash = api_hash.strip() or str(current.get("api_hash") or "")
    bot_token = bot_token.strip() or str(current.get("bot_token") or "")
    if not app_id.isdigit():
        raise TelegramError(400, "Enter the app id")
    if len(api_hash) < 8:
        raise TelegramError(400, "Enter the app API hash")
    if not _BOT_TOKEN.fullmatch(bot_token):
        raise TelegramError(400, "Enter the Telegram bot token from BotFather")
    payload = {
        "app_id": app_id,
        "api_hash": api_hash,
        "bot_token": bot_token,
        "paused_webhook": str(current.get("paused_webhook") or ""),
        "chat_id": str(current.get("chat_id") or ""),
        "update_offset": int(current.get("update_offset") or 0),
    }
    for key in ("user_session", "copy_chats", "copy_cursors", "user_connected", "phone", "phone_code_hash", "auto_execute", "trade_history"):
        if key in current:
            payload[key] = current[key]
    _write_telegram_secret(db, organization_id, payload)
    return {"app_id": app_id, "api_hash_set": True, "bot_token_set": True}


def telegram_bot_token(db: Session, organization_id: UUID) -> str:
    return str(_telegram_secret(db, organization_id).get("bot_token") or "")


def telegram_paused_webhook(db: Session, organization_id: UUID) -> str:
    return str(_telegram_secret(db, organization_id).get("paused_webhook") or "")


def apply_telegram_test_result(db: Session, organization_id: UUID, paused_webhook: str, chat_id: object) -> bool:
    current = _telegram_secret(db, organization_id)
    if not current:
        return False
    current["paused_webhook"] = paused_webhook
    if chat_id is not None:
        current["chat_id"] = str(chat_id)
    _write_telegram_secret(db, organization_id, current)
    return True


def drain_telegram_trades(db: Session) -> None:
    rows = db.scalars(select(TelegramConfig)).all()
    for row in rows:
        saved = _telegram_secret(db, row.organization_id)
        token = str(saved.get("bot_token") or "")
        if not _BOT_TOKEN.fullmatch(token):
            continue
        info = _telegram(token, "getWebhookInfo")
        if info.get("ok") and str((info.get("result") or {}).get("url") or ""):
            _telegram(token, "deleteWebhook", {"drop_pending_updates": False})
        params: dict = {"timeout": 0, "limit": 20}
        offset = int(saved.get("update_offset") or 0)
        if offset > 0:
            params["offset"] = offset
        updates = _telegram(token, "getUpdates", params)
        if not updates.get("ok"):
            continue
        last = offset
        for item in updates.get("result") or []:
            if not isinstance(item, dict):
                continue
            update_id = int(item.get("update_id") or 0)
            last = max(last, update_id + 1)
            message = item.get("message") if isinstance(item.get("message"), dict) else {}
            chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
            if not chat.get("id") or str(chat.get("type") or "private") != "private":
                continue
            photos = message.get("photo") if isinstance(message.get("photo"), list) else []
            file_id = str(photos[-1].get("file_id") or "") if photos and isinstance(photos[-1], dict) else ""
            if file_id:
                _handle_telegram_photo(db, row.organization_id, saved, token, chat, file_id, str(message.get("caption") or ""))
                continue
            text = str(message.get("text") or "").strip()
            if not text:
                continue
            _handle_telegram_instruction(db, row.organization_id, saved, token, chat, text)
        if last != offset:
            saved["update_offset"] = last
            _write_telegram_secret(db, row.organization_id, saved)


def _handle_telegram_instruction(db: Session, organization_id: UUID, saved: dict, token: str, chat: dict, text: str) -> None:
    from app.models.entities import Account, User
    from app.services.ai_service import run_trade_assistant
    from app.services.order_service import OrderError

    incoming = str(chat.get("id"))
    if not _allow_chat(saved, incoming, token):
        return
    if text.startswith("/start") or text.startswith("/help"):
        _telegram(token, "sendMessage", {"chat_id": incoming, "text": _telegram_help()})
        return
    from app.services.setup_watch import consider_setup

    setup = consider_setup(db, organization_id, incoming, text)
    if setup is not None:
        _remember_chat(saved, "user", text)
        _remember_chat(saved, "assistant", setup)
        _telegram(token, "sendMessage", {"chat_id": incoming, "text": setup[:3900]})
        return
    user = db.scalar(select(User).where(User.organization_id == organization_id, User.is_active.is_(True)).order_by(User.created_at))
    accounts = db.scalars(
        select(Account).where(Account.organization_id == organization_id, Account.connection_method == "metaapi", Account.ai_trading_enabled.is_(True))
    ).all()
    if user is None or not accounts:
        _telegram(token, "sendMessage", {"chat_id": incoming, "text": "Turn on Allow DeepSeek to trade on the account page, then send the instruction again."})
        return
    if len(accounts) > 1:
        _telegram(token, "sendMessage", {"chat_id": incoming, "text": "Leave DeepSeek trading on for one account, then send the instruction again."})
        return
    images: list[bytes] = []
    try:
        result = run_trade_assistant(db, user, accounts[0], text, images, source="Telegram", history=_chat_turns(saved))
        reply = _instruction_text(result)
    except OrderError as exc:
        reply = exc.detail
    except Exception:
        logger.exception("telegram_instruction_failed")
        reply = "DeepSeek could not run that instruction."
    _remember_chat(saved, "user", text)
    _remember_chat(saved, "assistant", reply)
    _telegram(token, "sendMessage", {"chat_id": incoming, "text": reply[:3900]})
    for image in images:
        _telegram_photo(token, incoming, image, "OpenAI image")


def _allow_chat(saved: dict, incoming: str, token: str) -> bool:
    allowed = str(saved.get("chat_id") or "")
    if allowed and incoming != allowed:
        _telegram(token, "sendMessage", {"chat_id": incoming, "text": "This chat cannot instruct the desk."})
        return False
    if not allowed:
        saved["chat_id"] = incoming
    return True


def _handle_telegram_photo(db: Session, organization_id: UUID, saved: dict, token: str, chat: dict, file_id: str, caption: str) -> None:
    from app.services.ai_service import AIProviderError, describe_image, openai_api_key

    incoming = str(chat.get("id"))
    if not _allow_chat(saved, incoming, token):
        return
    key = openai_api_key(db, organization_id)
    if not key:
        _telegram(token, "sendMessage", {"chat_id": incoming, "text": "Save an OpenAI API key in Settings. OpenAI asks only for that key."})
        return
    try:
        image, mime = _telegram_file(token, file_id)
        reply = describe_image(key, image, mime, caption)
    except (TelegramError, AIProviderError):
        reply = "OpenAI could not read that image."
    else:
        note = "Sent a chart image."
        if caption.strip():
            note = f"{note} {caption.strip()}"
        _remember_chat(saved, "user", note)
        _remember_chat(saved, "assistant", reply)
        from app.services.setup_watch import consider_setup

        setup = consider_setup(db, organization_id, incoming, f"{caption}\n\nImage: {reply}".strip(), from_image=True)
        if setup:
            _remember_chat(saved, "assistant", setup)
            reply = setup
    _telegram(token, "sendMessage", {"chat_id": incoming, "text": reply[:3900]})


def _telegram_file(token: str, file_id: str) -> tuple[bytes, str]:
    info = _telegram(token, "getFile", {"file_id": file_id})
    path = str((info.get("result") or {}).get("file_path") or "") if info.get("ok") else ""
    if not path or ".." in path:
        raise TelegramError(502, "Telegram did not return that image")
    url = f"https://api.telegram.org/file/bot{token}/{path}"
    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise TelegramError(502, "Telegram did not return that image") from exc
    if response.status_code >= 300 or not response.content or len(response.content) > 8_000_000:
        raise TelegramError(502, "Telegram did not return that image")
    mime = "image/png" if path.lower().endswith(".png") else "image/webp" if path.lower().endswith(".webp") else "image/jpeg"
    return response.content, mime


def _telegram_photo(token: str, chat_id: str, image: bytes, caption: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with httpx.Client(timeout=30) as client:
            client.post(url, data={"chat_id": chat_id, "caption": caption[:1000]}, files={"photo": ("image.png", image, "image/png")})
    except httpx.HTTPError:
        logger.exception("telegram_photo_failed")


def _stored_turns(saved: dict) -> list[dict]:
    raw = saved.get("trade_history")
    if not isinstance(raw, list):
        return []
    cutoff = time.time() - _HISTORY_TTL_SECONDS
    turns = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        try:
            at = float(item.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        if role not in {"user", "assistant"} or not content or at < cutoff:
            continue
        turns.append({"role": role, "content": content[:1500], "at": at})
    return turns[-_HISTORY_LIMIT:]


def _chat_turns(saved: dict) -> list[dict]:
    return [{"role": item["role"], "content": item["content"]} for item in _stored_turns(saved)]


def _remember_chat(saved: dict, role: str, content: str) -> None:
    text = content.strip()
    if role not in {"user", "assistant"} or not text:
        return
    turns = _stored_turns(saved)
    turns.append({"role": role, "content": text[:1500], "at": time.time()})
    saved["trade_history"] = turns[-_HISTORY_LIMIT:]


def _telegram_help() -> str:
    return (
        "Send a trade instruction in this chat. DeepSeek can open, change, or close trades on the account where it is allowed. "
        "Send a setup you are waiting for with the entry, stop, and target. I set the limit only after all three are read, then watch the price and tell you when it arrives. "
        "Examples: buy 0.02 VIX 75, close ticket 123, set ticket 123 to breakeven. "
        "Send a picture and OpenAI will read it. Ask for a picture when you need one and OpenAI will send it."
    )


def _instruction_text(result: dict) -> str:
    lines = [str(result.get("reply") or "Done.")]
    for step in result.get("steps") or []:
        outcome = step.get("result") if isinstance(step.get("result"), dict) else {}
        tool = str(step.get("tool") or "tool")
        if outcome.get("bid") or outcome.get("ask"):
            lines.append(f"{tool}: bid {outcome.get('bid') or '—'} ask {outcome.get('ask') or '—'}")
        elif outcome.get("image_ready"):
            lines.append(f"{tool}: image will be sent")
        elif "sent" in outcome:
            state = "sent" if outcome.get("sent") else "not sent"
            lines.append(f"{tool}: {state} {outcome.get('decision') or ''} {outcome.get('message') or ''}".strip())
    return "\n".join(lines)


def store_paused_webhook(db: Session, organization_id: UUID, url: str) -> bool:
    current = _telegram_secret(db, organization_id)
    if not current:
        return False
    current["paused_webhook"] = url
    _write_telegram_secret(db, organization_id, current)
    return True


def restore_webhook(token: str, url: str) -> None:
    if url:
        _telegram(token, "setWebhook", {"url": url})


def _telegram_secret(db: Session, organization_id: UUID) -> dict:
    row = db.scalar(select(TelegramConfig).where(TelegramConfig.organization_id == organization_id))
    if row is None or not row.secret_nonce or not row.secret_ciphertext:
        return {}
    return decrypt_json(row.secret_nonce, row.secret_ciphertext)


def _write_telegram_secret(db: Session, organization_id: UUID, payload: dict) -> None:
    nonce, ciphertext = encrypt_json(payload)
    row = db.scalar(select(TelegramConfig).where(TelegramConfig.organization_id == organization_id))
    if row is None:
        db.add(TelegramConfig(organization_id=organization_id, secret_nonce=nonce, secret_ciphertext=ciphertext))
        return
    row.secret_nonce = nonce
    row.secret_ciphertext = ciphertext
    row.updated_at = datetime.now(timezone.utc)


def _telegram(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(url, json=payload or {})
    except httpx.HTTPError as exc:
        raise TelegramError(502, "Telegram could not be reached") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return body if isinstance(body, dict) else {"ok": False}


def _latest_chat(updates: list) -> int | str | None:
    chat_id = None
    for item in updates:
        if not isinstance(item, dict):
            continue
        message = item.get("message") or item.get("edited_message") or item.get("my_chat_member") or {}
        chat = message.get("chat") if isinstance(message, dict) else None
        if isinstance(chat, dict) and chat.get("id") is not None:
            chat_id = chat["id"]
    return chat_id


def _public_telegram_error(payload: dict) -> str:
    text = str(payload.get("description") or "Telegram rejected the request")
    text = re.sub(r"\d{6,}:[A-Za-z0-9_-]+", "[token]", text)
    return text[:200]


class TelegramChannel:
    def send(self, chat_id: str, text: str) -> tuple[str, str]:
        settings = get_settings()
        if not settings.telegram_bot_token or not chat_id:
            return "not_configured", ""
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

        def call() -> httpx.Response:
            with httpx.Client(timeout=10) as client:
                return client.post(url, json={"chat_id": chat_id, "text": text})

        try:
            response = _telegram_breaker.call(call)
        except CircuitOpen:
            return "circuit_open", "telegram_circuit_open"
        except httpx.HTTPError:
            return "failed", "telegram_http"
        if response.status_code >= 300:
            return "failed", f"http_{response.status_code}"
        return "sent", ""


class SmsChannel:
    def send(self, to_number: str, text: str) -> tuple[str, str]:
        settings = get_settings()
        if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number and to_number):
            return "not_configured", ""
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"

        def call() -> httpx.Response:
            with httpx.Client(timeout=10) as client:
                return client.post(
                    url,
                    data={"To": to_number, "From": settings.twilio_from_number, "Body": text},
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                )

        try:
            response = _sms_breaker.call(call)
        except CircuitOpen:
            return "circuit_open", "sms_circuit_open"
        except httpx.HTTPError:
            return "failed", "sms_http"
        if response.status_code >= 300:
            return "failed", f"http_{response.status_code}"
        return "sent", ""


def raise_alert(
    db: Session,
    *,
    organization_id: UUID,
    account_id: UUID | None,
    alert_type: str,
    severity: str,
    title: str,
    body: str,
    dedupe_key: str,
    cooldown: timedelta = timedelta(minutes=30),
) -> Alert | None:
    if dedupe_key:
        since = datetime.now(timezone.utc) - cooldown
        existing = db.scalar(
            select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.created_at >= since)
        )
        if existing:
            return None
    alert = Alert(
        organization_id=organization_id,
        account_id=account_id,
        alert_type=alert_type,
        severity=severity,
        title=title,
        body=body,
        dedupe_key=dedupe_key,
        status="sent",
    )
    db.add(alert)
    db.flush()
    users = db.scalars(select(User).where(User.organization_id == organization_id, User.is_active.is_(True))).all()
    channels = {
        row.channel: row
        for row in db.scalars(select(AlertChannelConfig).where(AlertChannelConfig.organization_id == organization_id)).all()
    }
    for user in users:
        _deliver_in_app(db, alert, user)
        email_cfg = channels.get("email")
        if email_cfg is None or email_cfg.enabled:
            _deliver_email(db, alert, user, (email_cfg.destination if email_cfg and email_cfg.destination else user.email))
    hook = channels.get("webhook")
    if hook and hook.enabled and hook.destination:
        _deliver_outbound(db, alert, hook)
    telegram = channels.get("telegram")
    if telegram and telegram.enabled:
        _deliver_telegram(db, alert, telegram, users[0] if users else None)
    sms = channels.get("sms")
    if sms and sms.enabled:
        _deliver_sms(db, alert, sms, users[0] if users else None)
    return alert


def _deliver_in_app(db: Session, alert: Alert, user: User) -> None:
    note = Notification(
        alert_id=alert.id,
        user_id=user.id,
        channel="in_app",
        title=alert.title,
        body=alert.body,
        status="sent",
    )
    db.add(note)
    db.flush()
    db.add(NotificationDelivery(notification_id=note.id, channel="in_app", provider="database", status="sent"))


def _deliver_email(db: Session, alert: Alert, user: User, to_address: str) -> None:
    from app.services.mailer import Mailer

    note = Notification(
        alert_id=alert.id,
        user_id=user.id,
        channel="email",
        title=alert.title,
        body=alert.body,
        status="pending",
    )
    db.add(note)
    db.flush()
    from app.services.email_service import email_credentials

    api_key, sender = email_credentials(db, alert.organization_id)
    mailer = Mailer()
    try:
        status = _email_breaker.call(lambda: mailer.send(to_address, alert.title, alert.body, api_key=api_key, sender=sender))
        error = "" if status == "sent" else (mailer.last_error or status)
    except CircuitOpen:
        status, error = "circuit_open", "email_circuit_open"
    note.status = status
    db.add(NotificationDelivery(notification_id=note.id, channel="email", provider=mailer.provider or "smtp", status=status, error_code=error[:80]))


def _deliver_outbound(db: Session, alert: Alert, config: AlertChannelConfig) -> None:
    from app.core.encryption import decrypt_json

    secret = ""
    if config.secret_nonce and config.secret_ciphertext:
        secret = str(decrypt_json(config.secret_nonce, config.secret_ciphertext).get("secret") or "")
    body = f'{{"type":"{alert.alert_type}","title":"{alert.title}","severity":"{alert.severity}"}}'
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest() if secret else ""

    def call() -> httpx.Response:
        with httpx.Client(timeout=8) as client:
            return client.post(
                config.destination,
                content=body,
                headers={"Content-Type": "application/json", "X-Tradeguard-Signature": signature},
            )

    user = db.scalar(select(User).where(User.organization_id == alert.organization_id))
    if user is None:
        return
    note = Notification(alert_id=alert.id, user_id=user.id, channel="webhook", title=alert.title, body=alert.body)
    db.add(note)
    db.flush()
    try:
        response = _hook_breaker.call(call)
        status = "sent" if response.status_code < 300 else "failed"
        error = "" if status == "sent" else f"http_{response.status_code}"
    except CircuitOpen:
        status, error = "circuit_open", "webhook_circuit_open"
    except httpx.HTTPError:
        status, error = "failed", "webhook_http"
    note.status = status
    db.add(NotificationDelivery(notification_id=note.id, channel="webhook", provider="http", status=status, error_code=error))


def _deliver_telegram(db: Session, alert: Alert, config: AlertChannelConfig, user: User | None) -> None:
    if user is None:
        return
    status, error = TelegramChannel().send(config.destination, f"{alert.title}\n{alert.body}")
    note = Notification(alert_id=alert.id, user_id=user.id, channel="telegram", title=alert.title, body=alert.body, status=status)
    db.add(note)
    db.flush()
    db.add(NotificationDelivery(notification_id=note.id, channel="telegram", provider="telegram", status=status, error_code=error))


def _deliver_sms(db: Session, alert: Alert, config: AlertChannelConfig, user: User | None) -> None:
    if user is None:
        return
    status, error = SmsChannel().send(config.destination, f"{alert.title}: {alert.body}"[:300])
    note = Notification(alert_id=alert.id, user_id=user.id, channel="sms", title=alert.title, body=alert.body, status=status)
    db.add(note)
    db.flush()
    db.add(NotificationDelivery(notification_id=note.id, channel="sms", provider="twilio", status=status, error_code=error))

from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.database import get_db
from app.models.entities import UserNotificationChannel

router = APIRouter()

_CHAT_ID = re.compile(r"^-?\d{5,20}$")


class TelegramLinkIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=30)


def _channel_payload(row: UserNotificationChannel) -> dict:
    return {
        "id": str(row.id),
        "channel": row.channel,
        "destination": row.destination,
        "verified": row.verified,
        "connected_at": row.created_at.isoformat(),
    }


def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Fire a Telegram sendMessage and return True on success."""
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
        return resp.status_code == 200 and bool(resp.json().get("ok"))
    except Exception:  # noqa: BLE001
        return False


def _org_bot_token(db: Session, organization_id) -> str:
    """Retrieve the org-level Telegram bot token from the encrypted config."""
    from app.services.alert_service import telegram_bot_token

    return telegram_bot_token(db, organization_id)


def _bot_username(token: str) -> str:
    """Return the bot's @username or an empty string."""
    try:
        import httpx

        with httpx.Client(timeout=8) as client:
            resp = client.get(f"https://api.telegram.org/bot{token}/getMe")
        body = resp.json() if resp.status_code == 200 else {}
        return str(body.get("result", {}).get("username") or "")
    except Exception:  # noqa: BLE001
        return ""


@router.get("/notifications/telegram")
def get_telegram_link(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = db.scalar(
        select(UserNotificationChannel).where(
            UserNotificationChannel.user_id == principal.user.id,
            UserNotificationChannel.channel == "telegram",
        )
    )
    token = _org_bot_token(db, principal.user.organization_id)
    bot = _bot_username(token) if token else ""
    return {
        "connected": row is not None and row.verified,
        "chat_id": row.destination if row else "",
        "bot_username": bot,
    }


@router.post("/notifications/telegram")
def link_telegram(
    payload: TelegramLinkIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    chat_id = payload.chat_id.strip()
    if not _CHAT_ID.fullmatch(chat_id):
        raise HTTPException(400, "Enter a valid Telegram chat ID (digits only, may start with -).")

    token = _org_bot_token(db, principal.user.organization_id)
    if not token:
        raise HTTPException(400, "The platform Telegram bot has not been configured yet. Ask your administrator to set it up on the Telegram page.")

    verification_text = (
        f"✅ <b>Notifications connected</b>\n\n"
        f"Hi {principal.user.full_name or principal.user.email}, your TradeGuard account is now linked to this chat.\n"
        f"You will receive trade alerts, risk warnings, and account notifications here."
    )
    sent = _send_telegram(token, chat_id, verification_text)
    if not sent:
        raise HTTPException(502, "Could not reach that chat ID. Make sure you have already messaged the bot (it cannot initiate a conversation) and the ID is correct.")

    row = db.scalar(
        select(UserNotificationChannel).where(
            UserNotificationChannel.user_id == principal.user.id,
            UserNotificationChannel.channel == "telegram",
        )
    )
    if row is None:
        row = UserNotificationChannel(
            id=uuid4(),
            user_id=principal.user.id,
            channel="telegram",
            destination=chat_id,
            verified=True,
        )
        db.add(row)
    else:
        row.destination = chat_id
        row.verified = True

    db.commit()
    return _channel_payload(row)


@router.delete("/notifications/telegram")
def unlink_telegram(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = db.scalar(
        select(UserNotificationChannel).where(
            UserNotificationChannel.user_id == principal.user.id,
            UserNotificationChannel.channel == "telegram",
        )
    )
    if row is None:
        raise HTTPException(404, "Telegram is not connected.")
    db.delete(row)
    db.commit()
    return {"ok": True}

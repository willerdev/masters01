from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
RESEND_URL = "https://api.resend.com/emails"


class Mailer:
    def __init__(self) -> None:
        self.provider = ""
        self.last_error = ""

    def send(self, to: str, subject: str, body: str, *, api_key: str = "", sender: str = "") -> str:
        settings = get_settings()
        self.last_error = ""
        key = (api_key or settings.resend_api_key).strip()
        from_address = (sender or settings.resend_from or settings.smtp_from).strip()
        if key:
            self.provider = "resend"
            if not from_address or "@" not in from_address:
                self.last_error = "Add a from address on a domain verified in Resend"
                return "failed"
            return self._send_resend(key, from_address, to, subject, body)
        self.provider = "smtp"
        if not settings.smtp_host:
            logger.info("email_skipped_unconfigured to=%s subject=%s", to, subject)
            return "skipped_unconfigured"
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                if settings.smtp_tls:
                    client.starttls()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
        except OSError:
            logger.exception("email_send_failed")
            return "failed"
        return "sent"

    def _send_resend(self, api_key: str, sender: str, to: str, subject: str, body: str) -> str:
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(
                    RESEND_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "TradeGuard",
                    },
                    json={"from": sender, "to": [to], "subject": subject, "text": body},
                )
        except httpx.HTTPError:
            logger.exception("email_send_failed")
            self.last_error = "Resend could not be reached"
            return "failed"
        if response.status_code >= 300:
            self.last_error = _resend_message(response)
            logger.info("email_send_failed status=%s", response.status_code)
            return "failed"
        return "sent"


def _resend_message(response: httpx.Response) -> str:
    try:
        message = str(response.json().get("message") or "")
    except ValueError:
        message = ""
    return (message or f"Resend returned {response.status_code}")[:300]


class MemoryMailer(Mailer):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str, *, api_key: str = "", sender: str = "") -> str:
        self.messages.append((to, subject, body))
        self.provider = "resend" if api_key else "smtp"
        return "sent"

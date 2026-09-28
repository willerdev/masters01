from __future__ import annotations

from datetime import datetime, timedelta


def quote_is_stale(captured_at: datetime | None, now: datetime, max_age_seconds: int) -> bool:
    if captured_at is None:
        return True
    if captured_at.tzinfo is None or now.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=None)
        now = now.replace(tzinfo=None)
    return now - captured_at > timedelta(seconds=max_age_seconds)

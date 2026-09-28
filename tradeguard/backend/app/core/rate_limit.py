from __future__ import annotations

import time


class WindowLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = {}

    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        window = [stamp for stamp in self._buckets.get(key, []) if now - stamp < window_seconds]
        blocked = len(window) >= limit
        window.append(now)
        self._buckets[key] = window[-limit:]
        return blocked

    def reset(self) -> None:
        self._buckets.clear()


auth_limiter = WindowLimiter()

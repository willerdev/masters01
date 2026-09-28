from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitOpen(Exception):
    pass


class CircuitBreaker:
    """Small per-provider breaker. Closed after reset_seconds without a probe."""

    def __init__(self, fail_max: int = 5, reset_seconds: float = 30.0) -> None:
        self.fail_max = fail_max
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.reset_seconds:
            return False
        return True

    def call(self, func: Callable[[], T]) -> T:
        if self.is_open:
            raise CircuitOpen("circuit open")
        try:
            result = func()
        except Exception:
            self.failures += 1
            if self.failures >= self.fail_max:
                self.opened_at = time.monotonic()
            raise
        self.failures = 0
        self.opened_at = None
        return result

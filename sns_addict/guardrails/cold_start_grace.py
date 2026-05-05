"""Cold start grace period guardrail."""
from __future__ import annotations
import time


class ColdStartGrace:
    def __init__(self, start_time: float | None = None, grace_seconds: int = 300):
        self._start: float = start_time or time.time()
        self._grace: int = grace_seconds

    def is_active(self) -> bool:
        return time.time() - self._start < self._grace

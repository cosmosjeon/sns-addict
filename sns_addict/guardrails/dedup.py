"""Dedup guardrail — port from legacy adapter:114,274-278."""
from __future__ import annotations

import hashlib
import time

WINDOW_SECONDS = 600  # 10 minutes


class Dedup:
    def __init__(self):
        self._cache: dict[tuple[str, str], float] = {}

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def is_duplicate(self, thread_id: str, text: str) -> bool:
        key = (thread_id, self._hash(text))
        ts = self._cache.get(key)
        if ts is None:
            return False
        if time.time() - ts > WINDOW_SECONDS:
            del self._cache[key]
            return False
        return True

    def record(self, thread_id: str, text: str) -> None:
        key = (thread_id, self._hash(text))
        self._cache[key] = time.time()

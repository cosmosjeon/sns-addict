"""Loop detector guardrail — port from legacy adapter:510-520."""
from __future__ import annotations
import logging
import time

logger = logging.getLogger(__name__)

TURN_LIMIT = 4
WINDOW_SECONDS = 60


class LoopDetector:
    def __init__(self):
        self._turns: dict[str, list[float]] = {}
        self._frozen: set[str] = set()

    def is_frozen(self, thread_id: str) -> bool:
        return thread_id in self._frozen

    def record_turn(self, thread_id: str) -> None:
        now = time.time()
        turns = [t for t in self._turns.get(thread_id, []) if now - t < WINDOW_SECONDS]
        turns.append(now)
        self._turns[thread_id] = turns
        if len(turns) >= TURN_LIMIT:
            self._frozen.add(thread_id)
            logger.warning("Loop detected on thread %s — frozen", thread_id[:8])

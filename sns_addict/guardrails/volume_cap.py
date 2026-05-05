"""Volume cap guardrail — port from legacy adapter:315-343."""
from __future__ import annotations

import time

from sns_addict.persistence.state import StateStore, State

# Limits (verbatim from legacy)
DAY_LIMIT = 50
HOUR_FRIEND_LIMIT = 5
DAY_FRIEND_LIMIT = 20
DAY_WINDOW_SECONDS = 86400
HOUR_WINDOW_SECONDS = 3600


class VolumeCap:
    def __init__(self, state_store: StateStore):
        self._store: StateStore = state_store

    async def exceeded(self, thread_id: str) -> bool:
        state = await self._store.read()
        c = state.send_counters
        now = time.time()

        # Roll over day window if expired
        if now - c.day_window_start > DAY_WINDOW_SECONDS:
            return False  # will reset on record()

        # Global daily cap
        if c.day_count >= DAY_LIMIT:
            return True

        # Per-friend daily cap
        if c.per_friend_day.get(thread_id, 0) >= DAY_FRIEND_LIMIT:
            return True

        # Per-friend hourly cap
        hour_sends = [t for t in c.per_friend_hour.get(thread_id, []) if now - t < HOUR_WINDOW_SECONDS]
        if len(hour_sends) >= HOUR_FRIEND_LIMIT:
            return True

        return False

    async def record(self, thread_id: str) -> None:
        async def _update(state: State) -> State:
            c = state.send_counters
            now = time.time()
            # Roll over day window
            if now - c.day_window_start > DAY_WINDOW_SECONDS:
                c.day_window_start = now
                c.day_count = 0
                c.per_friend_day = {}
                c.per_friend_hour = {}
            c.day_count += 1
            c.per_friend_day[thread_id] = c.per_friend_day.get(thread_id, 0) + 1
            hour_list = c.per_friend_hour.get(thread_id, [])
            hour_list.append(now)
            c.per_friend_hour[thread_id] = hour_list
            return state

        _ = await self._store.update(_update)

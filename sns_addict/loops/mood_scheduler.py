"""Mood scheduler — time-of-day Korean mood cycles.

Cycles through four mood slots based on Asia/Seoul local time:
  아침  (morning):    06:00–11:59
  낮    (afternoon):  12:00–17:59
  저녁  (evening):    18:00–21:59
  밤    (night):      22:00–05:59

Current mood is written to state.json as ``current_mood`` (str).
InboundLoop reads this field when constructing the system prompt context.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sns_addict.persistence.state import State, StateStore

logger = logging.getLogger(__name__)

SEOUL_TZ = ZoneInfo("Asia/Seoul")

MOOD_MORNING = "아침"
MOOD_AFTERNOON = "낮"
MOOD_EVENING = "저녁"
MOOD_NIGHT = "밤"

_DEFAULT_POLL_INTERVAL = 60.0


def _current_seoul_hour() -> int:
    """Return the current hour (0–23) in Asia/Seoul. Patch this in tests."""
    return datetime.now(tz=SEOUL_TZ).hour


def get_current_mood() -> str:
    """Pure function — returns the Korean mood for the current Seoul hour.

    Boundaries (inclusive start, exclusive end):
        06:00–11:59 → 아침
        12:00–17:59 → 낮
        18:00–21:59 → 저녁
        22:00–05:59 → 밤
    """
    hour = _current_seoul_hour()
    if 6 <= hour < 12:
        return MOOD_MORNING
    if 12 <= hour < 18:
        return MOOD_AFTERNOON
    if 18 <= hour < 22:
        return MOOD_EVENING
    return MOOD_NIGHT


class MoodScheduler:
    """Polls the Seoul clock once per minute and updates ``state.current_mood``.

    Writes are skipped when the computed mood matches the persisted value, so
    state.json is only rewritten on a slot transition (≤ 4 times per day).
    """

    _store: StateStore
    _poll_interval: float
    _stop_event: asyncio.Event

    def __init__(
        self,
        store: StateStore | None = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._store = store if store is not None else StateStore()
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the scheduler loop until ``stop()`` is called."""
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:  # pragma: no cover — defensive log
                logger.exception("MoodScheduler tick failed")
            try:
                _ = await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        """Signal the scheduler loop to exit on the next iteration."""
        self._stop_event.set()

    async def _tick(self) -> None:
        """Read the current mood, compare to state, write only on change."""
        new_mood = get_current_mood()
        current = await self._store.read()
        if current.current_mood == new_mood:
            return

        def _apply(state: State) -> State:
            state.current_mood = new_mood
            state.mood_started_at = time.time()
            return state

        _ = await self._store.update(_apply)
        logger.info("Mood transitioned to %s", new_mood)

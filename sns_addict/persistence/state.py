"""Atomic state persistence for sns-addict."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, Union, cast

import aiofiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

STATE_PATH = Path.home() / ".hermes" / "sns-addict" / "state.json"

PENDING_LOST_SEC = 300  # mark sends pending > 5 min as lost (legacy adapter:567-577)


class SendCounters(BaseModel):
    day_window_start: float = Field(default_factory=time.time)
    day_count: int = 0
    per_friend_hour: dict[str, list[float]] = Field(default_factory=dict)
    per_friend_day: dict[str, int] = Field(default_factory=dict)


class State(BaseModel):
    version: int = 1
    current_mood: str = "평타"
    mood_started_at: float = Field(default_factory=time.time)
    last_seen_msg_id: str | None = None
    pending_sends: list[dict[str, Any]] = Field(default_factory=list)
    frozen_threads: list[str] = Field(default_factory=list)
    send_counters: SendCounters = Field(default_factory=SendCounters)
    session_state: Literal[
        "active", "paused", "stopped", "halted", "challenge_pending"
    ] = "stopped"
    halt_reason: str | None = None
    f3_mode: bool = False


StateCallback = Union[Callable[[State], State], Callable[[State], Awaitable[State]]]


class StateStore:
    """Atomic state persistence with corruption recovery.

    All instances share a single class-level lock so that concurrent
    `update()` calls from different StateStore instances pointing at the
    same file are still serialized.
    """

    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, path: Path = STATE_PATH):
        self._path = path

    async def read(self) -> State:
        if not self._path.exists():
            return State()
        try:
            async with aiofiles.open(self._path, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            state = State(**data)
        except Exception as exc:
            ts = int(time.time())
            backup = self._path.with_suffix(f".json.corrupt-{ts}")
            try:
                self._path.rename(backup)
            except Exception:
                pass
            logger.error(
                "state.json corrupted, backed up to %s: %s", backup, exc
            )
            return State()
        return self._age_pending_sends(state)

    async def write(self, state: State) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(state.model_dump_json(indent=2))
        os.rename(tmp, self._path)  # atomic on POSIX

    async def update(self, callback: StateCallback) -> State:
        async with self._lock:
            state = await self.read()
            if inspect.iscoroutinefunction(callback):
                async_cb = cast(Callable[[State], Awaitable[State]], callback)
                state = await async_cb(state)
            else:
                sync_cb = cast(Callable[[State], State], callback)
                state = sync_cb(state)
            await self.write(state)
            return state

    def _age_pending_sends(self, state: State) -> State:
        """Port of legacy adapter:567-577 — mark sends pending > 5min as lost."""
        now = time.time()
        for send in state.pending_sends:
            if send.get("status") != "pending":
                continue
            queued_at = send.get("queued_at", send.get("ts", now))
            if now - queued_at > PENDING_LOST_SEC:
                send["status"] = "lost"
        return state

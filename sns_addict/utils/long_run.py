"""Long-run hardening utilities for sns-addict.

Provides:
  - AutoStop: halts the adapter after 24h of continuous operation
  - SleepRecovery: detects OS sleep/wake gap > 30s and triggers reconnect
  - suspicious_login_log: logs suspicious-login events to evidence/suspicious_login.log
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

SUSPICIOUS_LOGIN_LOG = Path("evidence/suspicious_login.log")


class LongRunAdapter(Protocol):
    is_connected: bool

    async def halt(self, reason: str) -> None: ...

    async def connect(self) -> bool: ...

    async def disconnect(self) -> None: ...


class AutoStop:
    MAX_RUNTIME_SECONDS: int = 86400

    def __init__(self, adapter: LongRunAdapter) -> None:
        self._adapter: LongRunAdapter = adapter
        self._started_at: float = time.time()

    async def watch(self) -> None:
        while True:
            elapsed = time.time() - self._started_at
            remaining = self.MAX_RUNTIME_SECONDS - elapsed
            if remaining <= 0:
                logger.info("auto_stop_24h: runtime exceeded, halting")
                await self._adapter.halt("24h auto-stop")
                return
            await asyncio.sleep(min(remaining, 3600))


class SleepRecovery:
    SLEEP_GAP_THRESHOLD: float = 30.0
    TICK_INTERVAL: float = 5.0

    def __init__(self, adapter: LongRunAdapter) -> None:
        self._adapter: LongRunAdapter = adapter
        self._last_tick: float = time.time()

    async def watch(self) -> None:
        while True:
            await asyncio.sleep(self.TICK_INTERVAL)
            now = time.time()
            gap = now - self._last_tick - self.TICK_INTERVAL
            self._last_tick = now
            if gap > self.SLEEP_GAP_THRESHOLD:
                logger.warning(
                    "sleep_wake_detected: gap=%.1fs - reconnecting", gap
                )
                if self._adapter.is_connected:
                    await self._adapter.disconnect()
                    _ = await self._adapter.connect()


def suspicious_login_log(message: str) -> None:
    SUSPICIOUS_LOGIN_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = f"[{datetime.now(timezone.utc).isoformat()}] {message}\n"
    with open(SUSPICIOUS_LOGIN_LOG, "a", encoding="utf-8") as f:
        _ = f.write(entry)
    logger.warning(
        "suspicious_login_event: %s - see %s for manual review",
        message,
        SUSPICIOUS_LOGIN_LOG,
    )

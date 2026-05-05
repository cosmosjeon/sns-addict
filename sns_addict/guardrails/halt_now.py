"""HALT_NOW file watcher — port from legacy adapter:353-372."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

HALT_FILE = Path.home() / ".hermes" / "HALT_NOW"
SOUL_MD = Path.home() / ".hermes" / "SOUL.md"


class HaltAdapter(Protocol):
    async def halt(self, reason: str) -> None: ...

    async def disconnect(self) -> None: ...


class HaltNow:
    def is_present(self) -> bool:
        return HALT_FILE.expanduser().exists()

    async def watch(self, adapter: HaltAdapter, interval: float = 5.0) -> None:
        while True:
            await asyncio.sleep(interval)
            if self.is_present():
                logger.warning("HALT_NOW file detected — halting adapter")
                await adapter.halt("halt_now_file")
                await adapter.disconnect()
                return


async def watch_soul_md(interval: float = 30.0) -> None:
    """Watch SOUL.md mtime — log warning on change (C1: NO halt, just warn)."""
    last_mtime = SOUL_MD.stat().st_mtime if SOUL_MD.exists() else None
    while True:
        await asyncio.sleep(interval)
        try:
            current_mtime = SOUL_MD.stat().st_mtime if SOUL_MD.exists() else None
            if current_mtime != last_mtime:
                logger.warning(
                    "SOUL.md edited mid-run; hot-reload not supported in C1 "
                    + "(legacy halt behavior intentionally different)"
                )
                last_mtime = current_mtime
        except Exception:
            pass

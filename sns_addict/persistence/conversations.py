"""Conversations log — records thread interaction history for the dashboard.

Privacy: thread_id is stored as SHA-256 hex (first 16 chars), NEVER plaintext.
Schema per line (JSONL):
  {thread_id_hash: str, last_reply_ts: float, guardrail_state: str}
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)

CONVERSATIONS_PATH = Path.home() / ".hermes" / "sns-addict" / "conversations.jsonl"


def _hash_thread_id(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]


class ConversationsStore:
    """Append-only conversations log (JSONL).

    Each call to ``record`` appends one line. ``list_threads`` deduplicates by
    ``thread_id_hash``, keeping the most recent entry per hash, sorted by
    ``last_reply_ts`` descending.
    """

    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, path: Path = CONVERSATIONS_PATH):
        self._path = path

    async def record(self, thread_id: str, guardrail_state: str = "ok") -> None:
        """Append a new entry for ``thread_id`` (hashed before write)."""
        thread_id_hash = _hash_thread_id(thread_id)
        entry: dict[str, Any] = {
            "thread_id_hash": thread_id_hash,
            "last_reply_ts": time.time(),
            "guardrail_state": guardrail_state,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
                await f.write(line)

    async def _read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        async with aiofiles.open(self._path, "r", encoding="utf-8") as f:
            raw = await f.read()
        entries: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.debug("skipping malformed conversations line: %s", exc)
        return entries

    async def list_threads(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return up to ``limit`` deduplicated entries sorted by last_reply_ts desc."""
        entries = await self._read_all()
        latest: dict[str, dict[str, Any]] = {}
        for entry in entries:
            h = entry.get("thread_id_hash")
            if not isinstance(h, str):
                continue
            ts = entry.get("last_reply_ts", 0.0)
            existing = latest.get(h)
            if existing is None or ts > existing.get("last_reply_ts", 0.0):
                latest[h] = entry
        ordered = sorted(
            latest.values(),
            key=lambda e: e.get("last_reply_ts", 0.0),
            reverse=True,
        )
        return ordered[:limit]

    async def get_thread(self, thread_id_hash: str) -> dict[str, Any] | None:
        """Return the most recent entry for ``thread_id_hash`` or None."""
        entries = await self._read_all()
        match: dict[str, Any] | None = None
        for entry in entries:
            if entry.get("thread_id_hash") != thread_id_hash:
                continue
            if match is None or entry.get("last_reply_ts", 0.0) > match.get(
                "last_reply_ts", 0.0
            ):
                match = entry
        return match

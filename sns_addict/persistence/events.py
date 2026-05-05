"""Append-only events log (privacy: text always hashed)."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)

EVENTS_PATH = Path.home() / ".hermes" / "sns-addict" / "logs" / "events.jsonl"
MAX_SIZE_BYTES = 10 * 1024 * 1024


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def append_event(kind: str, **fields: Any) -> None:
    """Append one event line to events.jsonl. Text fields are NEVER stored plaintext."""
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if EVENTS_PATH.exists() and EVENTS_PATH.stat().st_size > MAX_SIZE_BYTES:
        ts = int(time.time())
        rotated = EVENTS_PATH.with_suffix(f".jsonl.{ts}")
        try:
            EVENTS_PATH.rename(rotated)
        except Exception as exc:
            logger.warning("events.jsonl rotation failed: %s", exc)

    if "text" in fields:
        fields["text_hash"] = _hash_text(str(fields.pop("text")))

    entry: dict[str, Any] = {"ts": time.time(), "kind": kind, **fields}
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    async with aiofiles.open(EVENTS_PATH, "a", encoding="utf-8") as f:
        await f.write(line)

"""Monitoring routes — events tail."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter()
_EVENTS_PATH = Path.home() / ".hermes" / "sns-addict" / "logs" / "events.jsonl"


@router.get("/events")
async def get_events(limit: int = 50) -> list[dict[str, Any]]:
    if not _EVENTS_PATH.exists():
        return []
    lines = _EVENTS_PATH.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-limit:] if len(lines) > limit else lines
    events: list[dict[str, Any]] = []
    for line in tail:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events

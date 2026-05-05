"""Control routes — start/stop/status/f3_mode."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sns_addict.persistence.state import StateStore
from sns_addict.persistence.events import append_event

logger = logging.getLogger(__name__)
router = APIRouter()
_store = StateStore()
_HALT_NOW = Path.home() / ".hermes" / "HALT_NOW"


@router.get("/status")
async def get_status() -> dict[str, Any]:
    state = await _store.read()
    return {
        "session_state": state.session_state,
        "current_mood": state.current_mood,
        "f3_mode": getattr(state, "f3_mode", False),
        "since": state.mood_started_at,
    }


@router.post("/start")
async def start_session() -> dict[str, Any]:
    async def _set_active(s: Any) -> Any:
        s.session_state = "active"
        return s
    await _store.update(_set_active)
    await append_event("control_signal", action="start")
    return {"ok": True, "session_state": "active"}


@router.post("/stop")
async def stop_session() -> dict[str, Any]:
    async def _set_stopped(s: Any) -> Any:
        s.session_state = "stopped"
        return s
    await _store.update(_set_stopped)
    await append_event("control_signal", action="stop")
    # Touch HALT_NOW to signal adapter
    _HALT_NOW.parent.mkdir(parents=True, exist_ok=True)
    _HALT_NOW.touch()
    return {"ok": True, "session_state": "stopped"}


class F3ModeRequest(BaseModel):
    enabled: bool
    collaborator_consent: bool = False


@router.post("/f3_mode")
async def set_f3_mode(req: F3ModeRequest) -> dict[str, Any]:
    if req.enabled and not req.collaborator_consent:
        raise HTTPException(
            status_code=422,
            detail="collaborator_consent must be True when enabling F3 mode",
        )
    async def _set_f3(s: Any) -> Any:
        s.f3_mode = req.enabled  # type: ignore[attr-defined]
        return s
    await _store.update(_set_f3)
    if req.enabled:
        await append_event("f3_mode_enabled", consent=req.collaborator_consent)
    return {"ok": True, "f3_mode": req.enabled}

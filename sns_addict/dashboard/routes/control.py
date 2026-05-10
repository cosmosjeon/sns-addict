"""Control routes — start/stop/status/f3_mode."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sns_addict.persistence.state import RuntimeMode, StateStore
from sns_addict.persistence.events import append_event
from sns_addict.runtime.supervisor import RuntimeSupervisor

logger = logging.getLogger(__name__)
router = APIRouter()
_store = StateStore()
_HALT_NOW = Path.home() / ".hermes" / "HALT_NOW"
_supervisor: RuntimeSupervisor | None = None


def _runtime_supervisor() -> RuntimeSupervisor:
    global _supervisor  # noqa: PLW0603
    if (
        _supervisor is None
        or _supervisor._state_store is not _store  # noqa: SLF001
        or _supervisor._halt_path != _HALT_NOW  # noqa: SLF001
    ):
        _supervisor = RuntimeSupervisor(state_store=_store, halt_path=_HALT_NOW)
    return _supervisor


@router.get("/status")
async def get_status() -> dict[str, Any]:
    state = await _store.read()
    return {
        "session_state": state.session_state,
        "runtime_mode": state.runtime_mode,
        "current_mood": state.current_mood,
        "f3_mode": getattr(state, "f3_mode", False),
        "since": state.mood_started_at,
        "runtime_health": _runtime_supervisor().health(),
        "approval_queue_count": len(
            [item for item in state.pending_sends if item.get("status") == "proposed"]
        ),
    }


@router.get("/llm_backend")
async def get_llm_backend_status() -> dict[str, Any]:
    return _runtime_supervisor().health().get(
        "llm_backend",
        {
            "backend_name": "Unknown",
            "available": False,
            "model": None,
            "setup_hint": "LLM backend status unavailable; drafts may fail.",
            "hermes_auxiliary_importable": False,
        },
    )


@router.post("/start")
async def start_session() -> dict[str, Any]:
    async def _set_active(s: Any) -> Any:
        s.session_state = "active"
        s.runtime_mode = "approval"
        return s
    _clear_halt_now()
    await _store.update(_set_active)
    await append_event("control_signal", action="start", runtime_mode="approval")
    health = await _runtime_supervisor().start("approval")
    return {
        "ok": True,
        "session_state": "active",
        "runtime_mode": "approval",
        "runtime_health": health,
    }


@router.post("/stop")
async def stop_session() -> dict[str, Any]:
    async def _set_stopped(s: Any) -> Any:
        s.session_state = "stopped"
        s.runtime_mode = "stopped"
        return s
    await _store.update(_set_stopped)
    await append_event("control_signal", action="stop")
    # Touch HALT_NOW to signal adapter
    _HALT_NOW.parent.mkdir(parents=True, exist_ok=True)
    _HALT_NOW.touch()
    health = await _runtime_supervisor().stop(touch_halt=True)
    return {
        "ok": True,
        "session_state": "stopped",
        "runtime_mode": "stopped",
        "runtime_health": health,
    }

def _clear_halt_now() -> None:
    try:
        _HALT_NOW.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("failed to clear HALT_NOW: %s", exc)


class RuntimeModeRequest(BaseModel):
    mode: RuntimeMode


@router.get("/mode")
async def get_runtime_mode() -> dict[str, Any]:
    state = await _store.read()
    return {"runtime_mode": state.runtime_mode, "session_state": state.session_state}


@router.post("/mode")
async def set_runtime_mode(req: RuntimeModeRequest) -> dict[str, Any]:
    async def _set_mode(s: Any) -> Any:
        s.runtime_mode = req.mode
        s.session_state = "stopped" if req.mode == "stopped" else "active"
        if req.mode != "stopped":
            s.halt_reason = None
        return s

    state = await _store.update(_set_mode)
    await append_event("runtime_mode_changed", runtime_mode=req.mode)
    if req.mode == "stopped":
        _HALT_NOW.parent.mkdir(parents=True, exist_ok=True)
        _HALT_NOW.touch()
        health = await _runtime_supervisor().stop(touch_halt=True)
    else:
        _clear_halt_now()
        health = await _runtime_supervisor().start(req.mode)
    return {
        "ok": True,
        "runtime_mode": state.runtime_mode,
        "session_state": state.session_state,
        "runtime_health": health,
    }


@router.get("/approval_queue")
async def get_approval_queue() -> dict[str, Any]:
    state = await _store.read()
    items = [
        item
        for item in state.pending_sends
        if item.get("status") in {"proposed", "approved", "sending", "failed"}
    ]
    items.sort(key=lambda item: float(item.get("queued_at", 0)), reverse=True)
    return {"items": items}


@router.post("/approval_queue/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> dict[str, Any]:
    now = time.time()
    changed: dict[str, Any] | None = None

    async def _approve(s: Any) -> Any:
        nonlocal changed
        for item in s.pending_sends:
            if item.get("id") == proposal_id:
                if item.get("status") != "proposed":
                    raise HTTPException(
                        status_code=409,
                        detail=f"proposal is {item.get('status', 'not proposed')}",
                    )
                item["status"] = "approved"
                item["approved_at"] = now
                changed = dict(item)
                return s
        raise HTTPException(status_code=404, detail="proposal not found")

    await _store.update(_approve)
    await append_event("reply_approved", proposal_id=proposal_id)
    return {"ok": True, "item": changed}


@router.post("/approval_queue/{proposal_id}/reject")
async def reject_proposal(proposal_id: str) -> dict[str, Any]:
    now = time.time()
    changed: dict[str, Any] | None = None

    async def _reject(s: Any) -> Any:
        nonlocal changed
        for item in s.pending_sends:
            if item.get("id") == proposal_id:
                if item.get("status") not in {"proposed", "approved", "failed"}:
                    raise HTTPException(
                        status_code=409,
                        detail=f"proposal is {item.get('status', 'not rejectable')}",
                    )
                item["status"] = "rejected"
                item["rejected_at"] = now
                changed = dict(item)
                return s
        raise HTTPException(status_code=404, detail="proposal not found")

    await _store.update(_reject)
    await append_event("reply_rejected", proposal_id=proposal_id)
    return {"ok": True, "item": changed}


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

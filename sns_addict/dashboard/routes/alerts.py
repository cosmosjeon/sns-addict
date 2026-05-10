"""Alerts routes — challenge/ban/quota panel."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from sns_addict.persistence.state import State, StateStore

router = APIRouter()
_store = StateStore()


@router.get("")
async def list_alerts() -> list[dict[str, Any]]:
    state = await _store.read()
    return [a for a in state.alerts if not a.get("dismissed", False)]


@router.post("/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str) -> dict[str, Any]:
    found = {"value": False}

    def _dismiss(s: State) -> State:
        for alert in s.alerts:
            if alert.get("id") == alert_id:
                alert["dismissed"] = True
                found["value"] = True
        return s

    await _store.update(_dismiss)
    if not found["value"]:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return {"ok": True}

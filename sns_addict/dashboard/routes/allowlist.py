"""Allowlist CRUD routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sns_addict.persistence.allowlist import AllowlistStore, Friend

router = APIRouter()
_store = AllowlistStore()

@router.get("/list")
async def list_friends() -> list[dict[str, Any]]:
    allowlist = await _store.read()
    return [f.model_dump() for f in allowlist.friends]

@router.post("/add")
async def add_friend(friend: Friend) -> dict[str, Any]:
    await _store.add(friend)
    allowlist = await _store.read()
    return {"ok": True, "count": len(allowlist.friends)}

@router.delete("/{username}")
async def remove_friend(username: str) -> dict[str, Any]:
    removed = await _store.remove(username)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Friend {username!r} not found")
    return {"ok": True}

@router.patch("/{username}")
async def update_friend(username: str, updates: dict[str, Any]) -> dict[str, Any]:
    friend = await _store.get(username)
    if friend is None:
        raise HTTPException(status_code=404, detail=f"Friend {username!r} not found")
    updated = friend.model_copy(update=updates)
    await _store.remove(username)
    await _store.add(updated)
    return {"ok": True, "friend": updated.model_dump()}

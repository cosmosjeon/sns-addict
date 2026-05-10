"""Conversations dashboard routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from sns_addict.persistence.conversations import ConversationsStore

router = APIRouter()
_store = ConversationsStore()


@router.get("")
async def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    return await _store.list_threads(limit=limit)


@router.get("/{thread_id_hash}")
async def get_conversation(thread_id_hash: str) -> dict[str, Any]:
    entry = await _store.get_thread(thread_id_hash)
    if entry is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return entry

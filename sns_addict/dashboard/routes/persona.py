# CYCLE 2 scope — placeholder for sns-addict realtime+mood phase
"""Persona routes — CYCLE 2 scope (501 stub)."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def persona_stub(path: str) -> None:
    raise HTTPException(status_code=501, detail="Cycle 2 scope — not implemented")

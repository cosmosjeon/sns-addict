# CYCLE 3 scope — placeholder for sns-addict challenge/ban/quota panel
"""Alerts routes — CYCLE 3 scope (501 stub)."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def alerts_stub(path: str) -> None:
    raise HTTPException(status_code=501, detail="Cycle 3 scope — not implemented")

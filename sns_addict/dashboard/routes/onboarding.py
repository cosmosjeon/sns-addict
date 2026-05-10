"""Onboarding routes for the non-developer dashboard flow."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from sns_addict.onboarding import InstagramLoginSupervisor, ensure_local_product_files

router = APIRouter()
_login_supervisor = InstagramLoginSupervisor()


@router.get("/instagram/status")
async def instagram_status() -> dict[str, Any]:
    ensure_local_product_files()
    return _login_supervisor.status()


@router.post("/instagram/connect")
async def instagram_connect() -> dict[str, Any]:
    return await _login_supervisor.connect()

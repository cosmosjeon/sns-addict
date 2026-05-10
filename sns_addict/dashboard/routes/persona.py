"""Persona editor routes — SOUL.md inline diff-preview + atomic write."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
SOUL_PATH = Path.home() / ".hermes" / "SOUL.md"


class _PreviewBody(BaseModel):
    proposed: str


class _CommitBody(BaseModel):
    content: str


def _ensure_utf8(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=422, detail=f"Content is not valid UTF-8: {exc}") from exc


async def _read_current() -> str:
    if not SOUL_PATH.exists():
        return ""
    async with aiofiles.open(SOUL_PATH, mode="r", encoding="utf-8") as f:
        return await f.read()


@router.get("")
async def get_persona() -> dict[str, str]:
    content = await _read_current()
    return {"content": content}


@router.post("/preview")
async def preview_persona(body: _PreviewBody) -> dict[str, Any]:
    _ensure_utf8(body.proposed)
    current = await _read_current()
    current_lines = current.splitlines(keepends=True)
    proposed_lines = body.proposed.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            current_lines,
            proposed_lines,
            fromfile="current",
            tofile="proposed",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines)
    lines_added = sum(
        1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
    )
    lines_removed = sum(
        1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
    )
    return {
        "diff": diff_text,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


@router.post("/commit")
async def commit_persona(body: _CommitBody) -> dict[str, Any]:
    encoded = _ensure_utf8(body.content)
    SOUL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = SOUL_PATH.with_suffix(".md.tmp")
    try:
        async with aiofiles.open(tmp_path, mode="wb") as f:
            await f.write(encoded)
        tmp_path.replace(SOUL_PATH)
    except Exception as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Atomic write failed: {exc}") from exc
    return {"ok": True, "bytes_written": len(encoded)}

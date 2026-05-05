"""Atomic allowlist persistence."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal

import aiofiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ALLOWLIST_PATH = Path.home() / ".hermes" / "sns-addict" / "allowlist.json"


class Friend(BaseModel):
    username: str
    display_name: str = ""
    friendliness: Literal["high", "medium", "low"] = "medium"
    topics: list[str] = Field(default_factory=list)
    added_at: float = Field(default_factory=time.time)
    is_collaborator: bool = False
    behavior_overrides: dict[str, Any] = Field(default_factory=dict)


class Allowlist(BaseModel):
    version: int = 1
    friends: list[Friend] = Field(default_factory=list)


class AllowlistStore:
    """Atomic allowlist persistence with corruption recovery."""

    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, path: Path = ALLOWLIST_PATH):
        self._path = path

    async def read(self) -> Allowlist:
        if not self._path.exists():
            return Allowlist()
        try:
            async with aiofiles.open(self._path, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            return Allowlist(**data)
        except Exception as exc:
            ts = int(time.time())
            backup = self._path.with_suffix(f".json.corrupt-{ts}")
            try:
                self._path.rename(backup)
            except Exception:
                pass
            logger.error(
                "allowlist.json corrupted, backed up to %s: %s", backup, exc
            )
            return Allowlist()

    async def write(self, allowlist: Allowlist) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(allowlist.model_dump_json(indent=2))
        os.rename(tmp, self._path)

    async def add(self, friend: Friend) -> Allowlist:
        async with self._lock:
            al = await self.read()
            al.friends = [f for f in al.friends if f.username != friend.username]
            al.friends.append(friend)
            await self.write(al)
            return al

    async def remove(self, username: str) -> Allowlist:
        async with self._lock:
            al = await self.read()
            al.friends = [f for f in al.friends if f.username != username]
            await self.write(al)
            return al

    async def get(self, username: str) -> Friend | None:
        al = await self.read()
        return next((f for f in al.friends if f.username == username), None)

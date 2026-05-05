"""Identity canary guardrail — port from legacy adapter:63-66,483-508."""
from __future__ import annotations
import hashlib
import json
import logging
import re
import time
from typing import Protocol
from pathlib import Path

logger = logging.getLogger(__name__)

IDENTITY_CANARY_PATTERNS = [
    r"ai야",
    r"사람.아니지",
    r"real person",
    r"are you human",
    r"\bai\b",
    r"\bbot\b",
    r"인공지능",
]

ALERTS_DIR = Path.home() / ".hermes" / "sns-addict" / "alerts"


class CanaryEvent(Protocol):
    thread_id: str


class CanaryAdapter(Protocol):
    async def send(self, thread_id: str, text: str) -> None: ...

    async def halt(self, reason: str) -> None: ...

    async def disconnect(self) -> None: ...


class IdentityCanary:
    CANONICAL_REPLY: str = "뭐래 ㅋㅋ"

    def __init__(self):
        self._patterns: list[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in IDENTITY_CANARY_PATTERNS
        ]

    def matches(self, text: str) -> bool:
        lower = text.lower()
        return any(p.search(lower) for p in self._patterns)

    async def handle(self, event: CanaryEvent, adapter: CanaryAdapter) -> None:
        await adapter.send(event.thread_id, self.CANONICAL_REPLY)
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        recovery = {
            "ts": time.time(),
            "thread_id_hash": hashlib.sha256(event.thread_id.encode()).hexdigest()[:16],
            "canonical_reply_sha256": hashlib.sha256(self.CANONICAL_REPLY.encode()).hexdigest(),
        }
        _ = (ALERTS_DIR / "identity_canary.json").write_text(
            json.dumps(recovery, indent=2, ensure_ascii=False)
        )
        await adapter.halt("identity_canary")
        await adapter.disconnect()
        logger.warning("Identity canary triggered — adapter halted")

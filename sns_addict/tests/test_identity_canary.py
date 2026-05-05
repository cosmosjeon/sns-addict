"""Tests for sns_addict.guardrails.identity_canary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class FakeEvent:
    thread_id: str


class FakeAdapter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.halts: list[str] = []
        self.disconnected: bool = False

    async def send(self, thread_id: str, text: str) -> None:
        self.sent.append((thread_id, text))

    async def halt(self, reason: str) -> None:
        self.halts.append(reason)

    async def disconnect(self) -> None:
        self.disconnected = True


def test_canary_korean_ai_pattern():
    from sns_addict.guardrails.identity_canary import IdentityCanary

    assert IdentityCanary().matches("너 ai야?") is True


def test_canary_english_pattern():
    from sns_addict.guardrails.identity_canary import IdentityCanary

    assert IdentityCanary().matches("are you human") is True


def test_canary_clean_text_no_hit():
    from sns_addict.guardrails.identity_canary import IdentityCanary

    assert IdentityCanary().matches("안녕 오늘 뭐해") is False


@pytest.mark.asyncio
async def test_canary_handle_writes_recovery_and_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import sns_addict.guardrails.identity_canary as identity_canary

    canary = identity_canary.IdentityCanary()
    adapter = FakeAdapter()
    event = FakeEvent(thread_id="thread-123")
    alerts_dir: Path = tmp_path / "alerts"
    monkeypatch.setattr(identity_canary, "ALERTS_DIR", alerts_dir)

    await canary.handle(event, adapter)

    assert adapter.sent == [("thread-123", "뭐래 ㅋㅋ")]
    assert adapter.halts == ["identity_canary"]
    assert adapter.disconnected is True

    payload = (alerts_dir / "identity_canary.json").read_text()
    assert "뭐래 ㅋㅋ" not in payload
    assert identity_canary.IdentityCanary.CANONICAL_REPLY == "뭐래 ㅋㅋ"
    assert (alerts_dir / "identity_canary.json").exists()

"""Tests for sns_addict.guardrails.halt_now."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class _Adapter:
    halt_calls: int
    disconnect_calls: int
    halt_reason: str

    def __init__(self) -> None:
        self.halt_calls = 0
        self.disconnect_calls = 0
        self.halt_reason = ""

    async def halt(self, reason: str) -> None:
        self.halt_calls += 1
        self.halt_reason = reason

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


def test_file_present_returns_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import sns_addict.guardrails.halt_now as halt_now

    halt_file: Path = tmp_path / ".hermes" / "HALT_NOW"
    halt_file.parent.mkdir(parents=True)
    halt_file.touch()
    monkeypatch.setattr(halt_now, "HALT_FILE", halt_file)

    assert halt_now.HaltNow().is_present() is True


def test_file_absent_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import sns_addict.guardrails.halt_now as halt_now

    halt_file: Path = tmp_path / ".hermes" / "HALT_NOW"
    monkeypatch.setattr(halt_now, "HALT_FILE", halt_file)

    assert halt_now.HaltNow().is_present() is False


@pytest.mark.asyncio
async def test_halt_now_watch_triggers_halt(tmp_path: Path):
    """watch() detects HALT_NOW file and calls adapter.halt + disconnect."""
    from sns_addict.guardrails.halt_now import HaltNow

    halt_file = tmp_path / "HALT_NOW"
    halt_file.touch()
    adapter = _Adapter()
    hn = HaltNow()
    with patch("sns_addict.guardrails.halt_now.HALT_FILE", halt_file):
        await hn.watch(adapter, interval=0.01)
    assert adapter.halt_calls == 1
    assert adapter.halt_reason == "halt_now_file"
    assert adapter.disconnect_calls == 1

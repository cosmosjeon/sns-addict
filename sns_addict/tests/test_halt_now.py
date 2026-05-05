"""Tests for sns_addict.guardrails.halt_now."""

from __future__ import annotations

from pathlib import Path

import pytest


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

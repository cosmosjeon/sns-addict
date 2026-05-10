"""Tests for sns_addict.loops.mood_scheduler — 4 time-slot moods."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import pytest

from sns_addict.loops import mood_scheduler


@pytest.mark.parametrize(
    "hour,expected",
    [
        (8, "아침"),
        (14, "낮"),
        (19, "저녁"),
        (23, "밤"),
    ],
    ids=["morning_08", "afternoon_14", "evening_19", "night_23"],
)
def test_get_current_mood_by_slot(
    monkeypatch: pytest.MonkeyPatch, hour: int, expected: str
) -> None:
    monkeypatch.setattr(mood_scheduler, "_current_seoul_hour", lambda: hour)
    assert mood_scheduler.get_current_mood() == expected

"""Tests for sns_addict.guardrails.loop_detector."""

from __future__ import annotations

from freezegun import freeze_time


@freeze_time("2026-05-05 12:00:00")
def test_4_turns_60s_freezes():
    from sns_addict.guardrails.loop_detector import LoopDetector

    detector = LoopDetector()
    for _ in range(4):
        detector.record_turn("thread-1")

    assert detector.is_frozen("thread-1") is True


@freeze_time("2026-05-05 12:00:00")
def test_60s_window_rolls_off():
    from sns_addict.guardrails.loop_detector import LoopDetector

    detector = LoopDetector()
    for _ in range(3):
        detector.record_turn("thread-1")

    with freeze_time("2026-05-05 12:01:01"):
        detector.record_turn("thread-1")
        assert detector.is_frozen("thread-1") is False


@freeze_time("2026-05-05 12:00:00")
def test_frozen_thread_blocks_send():
    from sns_addict.guardrails.loop_detector import LoopDetector

    detector = LoopDetector()
    for _ in range(4):
        detector.record_turn("thread-1")

    assert detector.is_frozen("thread-1") is True

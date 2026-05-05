"""Tests for sns_addict.guardrails.dedup."""

from __future__ import annotations

from freezegun import freeze_time


def test_dedup_same_content_same_thread_blocks():
    from sns_addict.guardrails.dedup import Dedup

    d = Dedup()
    d.record("thread-1", "hello")

    assert d.is_duplicate("thread-1", "hello") is True


def test_dedup_different_content_passes():
    from sns_addict.guardrails.dedup import Dedup

    d = Dedup()
    d.record("thread-1", "hello")

    assert d.is_duplicate("thread-1", "different") is False


@freeze_time("2026-05-05 12:00:00")
def test_dedup_10min_window_expires():
    from sns_addict.guardrails.dedup import Dedup

    d = Dedup()
    d.record("thread-1", "hello")

    with freeze_time("2026-05-05 12:10:05"):
        assert d.is_duplicate("thread-1", "hello") is False

"""Tests for ColdStartGrace guardrail."""
import time


def test_cold_start_grace_active_within_window():
    """Grace period is active within 5 minutes."""
    from sns_addict.guardrails.cold_start_grace import ColdStartGrace

    grace = ColdStartGrace(start_time=time.time(), grace_seconds=300)
    assert grace.is_active() is True


def test_cold_start_grace_inactive_after_window():
    """Grace period is inactive after 5 minutes."""
    from sns_addict.guardrails.cold_start_grace import ColdStartGrace

    past_start = time.time() - 301  # 5 min + 1 sec ago
    grace = ColdStartGrace(start_time=past_start, grace_seconds=300)
    assert grace.is_active() is False


def test_cold_start_grace_zero_seconds():
    """Grace period of 0 seconds is immediately inactive."""
    from sns_addict.guardrails.cold_start_grace import ColdStartGrace

    grace = ColdStartGrace(start_time=time.time(), grace_seconds=0)
    assert grace.is_active() is False


def test_cold_start_grace_default_start_time():
    """Default start_time is now — grace is active."""
    from sns_addict.guardrails.cold_start_grace import ColdStartGrace

    grace = ColdStartGrace()
    assert grace.is_active() is True

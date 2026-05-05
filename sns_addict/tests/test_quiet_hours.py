"""Tests for sns_addict.guardrails.quiet_hours."""

from __future__ import annotations

from freezegun import freeze_time


@freeze_time("2026-05-05 03:00:00")
def test_quiet_active_03_00():
    from sns_addict.guardrails.quiet_hours import QuietHours

    assert QuietHours().is_active() is True


@freeze_time("2026-05-05 09:00:00")
def test_quiet_inactive_09_00():
    from sns_addict.guardrails.quiet_hours import QuietHours

    assert QuietHours().is_active() is False

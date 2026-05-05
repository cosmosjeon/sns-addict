"""Tests for sns_addict.actions.humanize."""
# pyright: reportAny=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false

import pytest


def test_typing_delay_in_50_200_range():
    """Typing delay stays within the configured bounds."""
    from sns_addict.actions.humanize import Humanizer

    h = Humanizer()
    delays = [h.next_typing_delay() for _ in range(100)]

    assert all(50 <= d <= 200 for d in delays)


def test_pause_kinds():
    """Pause kinds map to their expected ranges."""
    from sns_addict.actions.humanize import Humanizer

    h = Humanizer()
    assert all(2 <= h.next_pause("thinking") <= 30 for _ in range(100))
    assert all(0.3 <= h.next_pause("send") <= 1.5 for _ in range(100))
    assert all(0.5 <= h.next_pause("scroll") <= 3.0 for _ in range(100))


def test_should_take_break_5pct(monkeypatch: pytest.MonkeyPatch):
    """Break rate is roughly 5 percent."""
    from sns_addict.actions.humanize import Humanizer

    h = Humanizer()
    values = [0.01] * 50 + [0.99] * 950
    it = iter(values)
    monkeypatch.setattr("sns_addict.actions.humanize.random.random", lambda: next(it))

    hits = sum(h.should_take_break() for _ in range(1000))
    ratio = hits / 1000

    assert ratio == pytest.approx(0.05, abs=0.03)

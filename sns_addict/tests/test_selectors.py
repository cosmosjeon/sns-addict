"""Tests for Instagram selector drift resistance."""

from __future__ import annotations


def test_dm_thread_item_matches_absolute_and_relative_direct_thread_links() -> None:
    from sns_addict.browser.selectors import SELECTORS

    selectors = SELECTORS["dm_thread_item"]

    assert 'a[href*="/direct/t/"]' in selectors
    assert 'a[href^="/direct/t/"]' not in selectors


def test_dom_observer_scans_absolute_and_relative_direct_thread_links() -> None:
    from sns_addict.detection.dom_observer import _OBSERVER_SCRIPT

    assert 'a[href*="/direct/t/"]' in _OBSERVER_SCRIPT
    assert 'a[href^="/direct/t/"]' not in _OBSERVER_SCRIPT

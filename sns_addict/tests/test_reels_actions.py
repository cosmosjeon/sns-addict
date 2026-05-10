"""Tests for sns_addict.actions.reels and sns_addict.actions.story."""
# pyright: reportAny=false, reportUnusedCallResult=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnknownParameterType=false

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakePlaywrightError(Exception):
    pass


def _build_locator() -> MagicMock:
    locator = MagicMock()
    locator.first = locator
    locator.wait_for = AsyncMock()
    locator.click = AsyncMock()
    return locator


def _build_page() -> MagicMock:
    page = MagicMock()
    page.goto = AsyncMock()
    page.locator = MagicMock(return_value=_build_locator())
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    return page


def _build_humanizer() -> MagicMock:
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0.0)
    humanizer.next_typing_delay = MagicMock(return_value=10)
    return humanizer


@pytest.mark.asyncio
async def test_share_reel_success():
    from sns_addict.actions.reels import ReelsActions

    page = _build_page()
    actions = ReelsActions(page, _build_humanizer())

    with patch("sns_addict.actions.reels.asyncio.sleep", new=AsyncMock()):
        result = await actions.share_reel(
            "https://www.instagram.com/reel/abc/", "thread-xyz"
        )

    assert result is True
    page.goto.assert_awaited_once()


@pytest.mark.asyncio
async def test_share_reel_dom_failure():
    from sns_addict.actions.reels import ReelsActions

    page = _build_page()
    page.goto = AsyncMock(side_effect=_FakePlaywrightError("locator timeout"))
    actions = ReelsActions(page, _build_humanizer())

    with patch("sns_addict.actions.reels.asyncio.sleep", new=AsyncMock()):
        result = await actions.share_reel(
            "https://www.instagram.com/reel/abc/", "thread-xyz"
        )

    assert result is False


@pytest.mark.asyncio
async def test_story_react_success():
    from sns_addict.actions.story import StoryActions

    page = _build_page()
    actions = StoryActions(page, _build_humanizer())

    with patch("sns_addict.actions.story.asyncio.sleep", new=AsyncMock()):
        result = await actions.react_to_story(
            "https://www.instagram.com/stories/user/123/", "❤️"
        )

    assert result is True
    page.goto.assert_awaited_once()
    assert page.keyboard.type.await_count >= 1


@pytest.mark.asyncio
async def test_story_react_dom_failure():
    from sns_addict.actions.story import StoryActions

    page = _build_page()
    failing_locator = MagicMock()
    failing_locator.first = failing_locator
    failing_locator.wait_for = AsyncMock(
        side_effect=_FakePlaywrightError("not visible")
    )
    failing_locator.click = AsyncMock()
    page.locator = MagicMock(return_value=failing_locator)
    actions = StoryActions(page, _build_humanizer())

    with patch("sns_addict.actions.story.asyncio.sleep", new=AsyncMock()):
        result = await actions.react_to_story(
            "https://www.instagram.com/stories/user/123/", "❤️"
        )

    assert result is False

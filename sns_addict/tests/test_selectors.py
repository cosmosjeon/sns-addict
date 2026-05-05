"""Tests for sns_addict.browser.selectors."""
# pyright: reportAny=false, reportUnusedImport=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnusedCallResult=false
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_click_first_matching_first_works():
    """First selector matches — returns True, click called once."""
    from sns_addict.browser.selectors import click_first_matching, SELECTORS

    page = MagicMock()
    locator = MagicMock()
    locator.first = locator
    locator.wait_for = AsyncMock(return_value=None)
    locator.click = AsyncMock()
    page.locator = MagicMock(return_value=locator)

    result = await click_first_matching(page, "dm_inbox_link")

    assert result is True
    page.locator.assert_called()
    locator.click.assert_called_once()


@pytest.mark.asyncio
async def test_click_first_matching_second_falls_back():
    """First selector fails, second succeeds."""
    from sns_addict.browser.selectors import click_first_matching, SELECTORS

    call_count = 0

    def locator_factory(_selector):
        nonlocal call_count
        call_count += 1
        locator = MagicMock()
        locator.first = locator
        locator.click = AsyncMock()
        if call_count == 1:
            locator.wait_for = AsyncMock(side_effect=Exception("not visible"))
        else:
            locator.wait_for = AsyncMock(return_value=None)
        return locator

    page = MagicMock()
    page.locator = MagicMock(side_effect=locator_factory)

    result = await click_first_matching(page, "dm_inbox_link")

    assert result is True


@pytest.mark.asyncio
async def test_click_first_matching_all_fail_raises():
    """All selectors fail — raises RuntimeError."""
    from sns_addict.browser.selectors import click_first_matching

    page = MagicMock()
    locator = MagicMock()
    locator.first = locator
    locator.wait_for = AsyncMock(side_effect=Exception("nope"))
    page.locator = MagicMock(return_value=locator)

    with pytest.raises(RuntimeError):
        await click_first_matching(page, "dm_inbox_link")


@pytest.mark.asyncio
async def test_click_first_matching_visibility_check():
    """Selector matches but element not visible — tries next fallback."""
    from sns_addict.browser.selectors import click_first_matching, SELECTORS

    assert len(SELECTORS) >= 9
    page = MagicMock()
    locator = MagicMock()
    locator.first = locator
    locator.wait_for = AsyncMock(side_effect=Exception("hidden"))
    locator.click = AsyncMock()
    page.locator = MagicMock(return_value=locator)

    with pytest.raises(RuntimeError):
        await click_first_matching(page, "dm_inbox_link")

    locator.click.assert_not_called()

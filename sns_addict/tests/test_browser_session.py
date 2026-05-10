"""Tests for sns_addict.browser.session.BrowserSession."""
# pyright: reportAny=false, reportPrivateUsage=false
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.mark.asyncio
async def test_start_creates_persistent_context():
    """BrowserSession.start() calls launch_persistent_context with correct kwargs."""
    from sns_addict.browser.session import BrowserSession

    profile_dir = Path("/tmp/test-profile")
    session = BrowserSession(profile_dir)
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.pages = []
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = AsyncMock()
    mock_browser.launch_persistent_context = AsyncMock(return_value=mock_context)
    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_browser
    mock_playwright_start = AsyncMock(return_value=mock_playwright)
    mock_async_playwright = MagicMock()
    mock_async_playwright.start = mock_playwright_start

    with patch("sns_addict.browser.session.async_playwright", return_value=mock_async_playwright):
        result = await session.start()

    mock_browser.launch_persistent_context.assert_called_once()
    call_kwargs = mock_browser.launch_persistent_context.call_args[1]
    assert call_kwargs.get("headless") is False
    assert call_kwargs.get("locale") == "ko-KR"
    assert "channel" not in call_kwargs
    assert result is mock_page


@pytest.mark.asyncio
async def test_is_logged_in_true():
    """is_logged_in returns True when logged-in selector found."""
    from sns_addict.browser.session import BrowserSession

    session = BrowserSession(Path("/tmp/test-profile"))
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.first = mock_locator
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.is_visible = AsyncMock(return_value=True)
    mock_page.locator = MagicMock(return_value=mock_locator)
    session._page = mock_page

    result = await session.is_logged_in()

    assert result is True


@pytest.mark.asyncio
async def test_is_logged_in_false():
    """is_logged_in returns False when selector times out."""
    from sns_addict.browser.session import BrowserSession

    session = BrowserSession(Path("/tmp/test-profile"))
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.first = mock_locator
    mock_locator.count = AsyncMock(side_effect=Exception("Timeout"))
    mock_page.locator = MagicMock(return_value=mock_locator)
    session._page = mock_page

    result = await session.is_logged_in()

    assert result is False


@pytest.mark.asyncio
async def test_stop_idempotent():
    """stop() without start() raises no exception."""
    from sns_addict.browser.session import BrowserSession

    session = BrowserSession(Path("/tmp/test-profile"))
    # Should not raise
    await session.stop()


def test_missing_browser_error_detects_patchright_executable_message() -> None:
    from sns_addict.browser.session import _is_missing_browser_error

    exc = RuntimeError(
        "BrowserType.launch_persistent_context: Executable doesn't exist at /tmp/x/Chromium"
    )

    assert _is_missing_browser_error(exc) is True

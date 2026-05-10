"""Tests for sns_addict.actions.dm."""
# pyright: reportAny=false, reportUnusedCallResult=false, reportUnknownParameterType=false, reportMissingParameterType=false

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_send_typing_uses_humanizer_per_char():
    """Typing calls keyboard.type once per character."""
    from sns_addict.actions.dm import DMActions

    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_typing_delay = MagicMock(return_value=123)
    humanizer.next_pause = MagicMock(return_value=0.3)
    actions = DMActions(page, humanizer)

    with patch.object(actions, "_navigate_to_thread", AsyncMock()), patch(
        "sns_addict.actions.dm.click_first_matching", new=AsyncMock(return_value=True)
    ), patch("sns_addict.actions.dm.asyncio.sleep", new=AsyncMock()):
        await actions.send("thread-1", "hey")

    assert page.keyboard.type.await_count == len("hey")
    assert humanizer.next_typing_delay.call_count == len("hey")


@pytest.mark.asyncio
async def test_send_clicks_send_button():
    """Send flow clicks the send button selector."""
    from sns_addict.actions.dm import DMActions

    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_typing_delay = MagicMock(return_value=123)
    humanizer.next_pause = MagicMock(return_value=0.3)
    actions = DMActions(page, humanizer)

    mock_click = AsyncMock(return_value=True)
    with patch.object(actions, "_navigate_to_thread", AsyncMock()), patch(
        "sns_addict.actions.dm.click_first_matching", new=mock_click
    ), patch("sns_addict.actions.dm.asyncio.sleep", new=AsyncMock()):
        await actions.send("thread-1", "ok")

    assert any(call.args[1] == "dm_send_button" for call in mock_click.await_args_list)


@pytest.mark.asyncio
async def test_send_no_retry_on_failure():
    """Failures bubble up immediately with no retry."""
    from sns_addict.actions.dm import DMActions

    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_typing_delay = MagicMock(return_value=123)
    humanizer.next_pause = MagicMock(return_value=0.3)
    actions = DMActions(page, humanizer)

    mock_click = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(actions, "_navigate_to_thread", AsyncMock()), patch(
        "sns_addict.actions.dm.click_first_matching", new=mock_click
    ), patch("sns_addict.actions.dm.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError):
            await actions.send("thread-1", "ok")

    assert mock_click.await_count == 1


@pytest.mark.asyncio
async def test_read_thread_extracts_messages():
    """read_thread returns parsed message dictionaries."""
    from sns_addict.actions.dm import DMActions

    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value=[
            {"text": "hello", "is_self": False},
            {"text": "hi", "is_self": True},
        ]
    )
    humanizer = MagicMock()
    actions = DMActions(page, humanizer)

    with patch.object(actions, "_navigate_to_thread", AsyncMock()), patch(
        "sns_addict.actions.dm.asyncio.sleep", new=AsyncMock()
    ):
        messages = await actions.read_thread("thread-1", limit=2)

    assert messages == [
        {"text": "hello", "is_self": False},
        {"text": "hi", "is_self": True},
    ]


@pytest.mark.asyncio
async def test_list_inbox_threads_returns_unread_marker():
    """Inbox listing preserves unread markers from evaluate()."""
    from sns_addict.actions.dm import DMActions

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(
        return_value=[
            {"href": "https://www.instagram.com/direct/t/123/", "title": "A", "unread": True},
            {"href": "https://www.instagram.com/direct/t/456/", "title": "B", "unread": False},
        ]
    )
    humanizer = MagicMock()
    actions = DMActions(page, humanizer)

    threads = await actions.list_inbox_threads()

    assert threads[0]["unread"] is True
    assert threads[1]["unread"] is False


@pytest.mark.asyncio
async def test_list_inbox_threads_does_not_require_direct_anchor_selector():
    """Inbox polling should still snapshot rows when IG hides /direct/t/ anchors."""
    from sns_addict.actions.dm import DMActions

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(side_effect=TimeoutError("no direct anchors"))
    page.evaluate = AsyncMock(
        return_value=[
            {
                "href": "",
                "title": "friend",
                "text": "friend\n새 메시지",
                "unread": True,
            }
        ]
    )
    humanizer = MagicMock()
    actions = DMActions(page, humanizer)

    threads = await actions.list_inbox_threads()

    page.wait_for_selector.assert_not_awaited()
    assert threads[0]["unread"] is True


@pytest.mark.asyncio
async def test_resolve_inbox_thread_href_clicks_row_without_anchor():
    """When IG hides direct anchors, click the row and read location.href."""
    from sns_addict.actions.dm import DMActions

    row = MagicMock()
    row.click = AsyncMock(return_value=None)
    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value="https://www.instagram.com/direct/t/abc123/")
    humanizer = MagicMock()
    actions = DMActions(page, humanizer)

    with patch(
        "sns_addict.actions.dm.query_all_matching",
        new=AsyncMock(return_value=[row]),
    ), patch("sns_addict.actions.dm.asyncio.sleep", new=AsyncMock()):
        href = await actions.resolve_inbox_thread_href(row_index=0)

    row.click.assert_awaited_once()
    assert href == "https://www.instagram.com/direct/t/abc123/"

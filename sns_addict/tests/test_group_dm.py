"""Tests for sns_addict.actions.group.GroupDMActions."""

# pyright: reportAny=false, reportUnusedCallResult=false

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from sns_addict.persistence.state import State


def _make_state_store(state: State):
    store = MagicMock()
    store.read = AsyncMock(return_value=state)

    async def _update(callback):
        if callable(callback):
            result = callback(state)
            if hasattr(result, "__await__"):
                return await result
            return result
        return state

    store.update = AsyncMock(side_effect=_update)
    return store


def _make_page() -> MagicMock:
    page = MagicMock()
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.evaluate = AsyncMock(return_value=[])
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    return page


@pytest.mark.asyncio
async def test_read_group_thread_returns_messages():
    """Mock page.evaluate returns DOM dump → read_group_thread surfaces it as list[dict]."""
    from sns_addict.actions.group import GroupDMActions

    page = _make_page()
    fake_msgs = [
        {"text": "안녕", "is_self": False},
        {"text": "ㅋㅋ", "is_self": True},
    ]
    page.evaluate = AsyncMock(return_value=fake_msgs)

    actions = GroupDMActions(state_store=_make_state_store(State()))
    result = await actions.read_group_thread(page, "group-abc", limit=5)

    assert result == fake_msgs
    page.goto.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_group_dm_success():
    """Counter under cap → send fires, returns True, counter incremented."""
    from sns_addict.actions.group import GroupDMActions

    state = State(
        group_send_counters={"group-a": 3},
        group_send_window_start=time.time(),
    )
    store = _make_state_store(state)
    page = _make_page()

    actions = GroupDMActions(state_store=store)
    result = await actions.send_group_dm(page, "group-a", "hello")

    assert result is True
    page.fill.assert_awaited_once()
    page.keyboard.press.assert_awaited_once_with("Enter")
    store.update.assert_awaited()
    assert state.group_send_counters["group-a"] == 4


@pytest.mark.asyncio
async def test_group_cap_enforced():
    """group_id at 15/15 → returns False, page never touched, no counter bump."""
    from sns_addict.actions.group import GroupDMActions

    state = State(
        group_send_counters={"group-a": 15},
        group_send_window_start=time.time(),
    )
    store = _make_state_store(state)
    page = _make_page()

    actions = GroupDMActions(state_store=store)
    result = await actions.send_group_dm(page, "group-a", "hello")

    assert result is False
    page.fill.assert_not_called()
    page.keyboard.press.assert_not_called()
    store.update.assert_not_called()
    assert state.group_send_counters["group-a"] == 15


@pytest.mark.asyncio
async def test_multi_group_isolation():
    """group-a at cap → group-b (under cap) can still send."""
    from sns_addict.actions.group import GroupDMActions

    state = State(
        group_send_counters={"group-a": 15, "group-b": 0},
        group_send_window_start=time.time(),
    )
    store = _make_state_store(state)
    page_a = _make_page()
    page_b = _make_page()

    actions = GroupDMActions(state_store=store)
    blocked = await actions.send_group_dm(page_a, "group-a", "no")
    allowed = await actions.send_group_dm(page_b, "group-b", "yes")

    assert blocked is False
    assert allowed is True
    page_a.fill.assert_not_called()
    page_b.fill.assert_awaited_once()
    assert state.group_send_counters["group-a"] == 15
    assert state.group_send_counters["group-b"] == 1

"""Tests for sns_addict.loops.active_behavior.ActiveBehavior."""

# pyright: reportAny=false, reportUnusedCallResult=false

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sns_addict.persistence.allowlist import Allowlist, Friend
from sns_addict.persistence.state import State


def _build(
    *,
    mood: str = "낮",
    friends: list[str] | None = None,
    volume_exceeded: bool = False,
):
    from sns_addict.loops.active_behavior import ActiveBehavior

    state_store = MagicMock()
    state_store.read = AsyncMock(return_value=State(current_mood=mood))

    allowlist_store = MagicMock()
    allowlist_store.read = AsyncMock(
        return_value=Allowlist(
            friends=[Friend(username=u) for u in (friends or [])]
        )
    )

    volume_cap = MagicMock()
    volume_cap.exceeded = AsyncMock(return_value=volume_exceeded)
    volume_cap.record = AsyncMock()

    adapter = MagicMock()
    adapter.send = AsyncMock()

    behavior = ActiveBehavior(
        state_store=state_store,
        allowlist_store=allowlist_store,
        volume_cap=volume_cap,
    )
    return behavior, adapter, volume_cap


@pytest.mark.asyncio
async def test_volume_cap_enforced():
    """Volume cap exceeded → returns False, adapter.send not called."""
    behavior, adapter, volume_cap = _build(
        friends=["friend-1"],
        volume_exceeded=True,
    )

    result = await behavior.send_active_dm(adapter, "friend-1", "hi")

    assert result is False
    adapter.send.assert_not_called()
    volume_cap.record.assert_not_called()


@pytest.mark.asyncio
async def test_mood_gate_night_blocked():
    """Mood == "밤" → returns False, allowlist/volume never checked, no send."""
    behavior, adapter, volume_cap = _build(mood="밤", friends=["friend-1"])

    result = await behavior.send_active_dm(adapter, "friend-1", "hi")

    assert result is False
    volume_cap.exceeded.assert_not_called()
    adapter.send.assert_not_called()


@pytest.mark.asyncio
async def test_allowlist_check():
    """thread_id absent from allowlist → returns False, no send."""
    behavior, adapter, volume_cap = _build(friends=["someone-else"])

    result = await behavior.send_active_dm(adapter, "stranger", "hi")

    assert result is False
    volume_cap.exceeded.assert_not_called()
    adapter.send.assert_not_called()

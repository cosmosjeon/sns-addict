"""Tests for sns_addict.loops.inbound.InboundLoop."""

# pyright: reportAny=false, reportUnusedCallResult=false

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_event(thread_id: str = "t1", text: str = "안녕", ts: float | None = None) -> dict[str, object]:
    return {"thread_id": thread_id, "text": text, "ts": ts or time.time(), "message_id": "m1"}


def make_guardrails(
    canary_matches: bool = False,
    quiet_active: bool = False,
    loop_frozen: bool = False,
    dedup_duplicate: bool = False,
    volume_exceeded: bool = False,
):
    from sns_addict.loops.inbound import GuardrailsBundle

    canary = MagicMock()
    canary.matches = MagicMock(return_value=canary_matches)
    canary.handle = AsyncMock()

    quiet = MagicMock()
    quiet.is_active = MagicMock(return_value=quiet_active)

    loop_det = MagicMock()
    loop_det.is_frozen = MagicMock(return_value=loop_frozen)
    loop_det.record_turn = MagicMock()

    dedup = MagicMock()
    dedup.is_duplicate = MagicMock(return_value=dedup_duplicate)
    dedup.record = MagicMock()

    volume = MagicMock()
    volume.exceeded = MagicMock(return_value=volume_exceeded)
    volume.record = MagicMock()

    return GuardrailsBundle(
        canary=canary,
        quiet_hours=quiet,
        loop_detector=loop_det,
        dedup=dedup,
        volume=volume,
    )


@pytest.mark.asyncio
async def test_canary_first_short_circuit():
    """Canary match → LLM/dedup/volume never called."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(canary_matches=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(adapter=adapter, guardrails=guardrails, humanizer=humanizer)

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    guardrails.canary.handle.assert_called_once()
    adapter.invoke_llm.assert_not_called()
    adapter.send.assert_not_called()
    guardrails.dedup.is_duplicate.assert_not_called()
    guardrails.volume.exceeded.assert_not_called()


@pytest.mark.asyncio
async def test_quiet_hours_drops_event():
    """Quiet hours active → reply never sent."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(quiet_active=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(adapter=adapter, guardrails=guardrails, humanizer=humanizer)

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    adapter.invoke_llm.assert_not_called()
    calls = [str(c) for c in mock_append.call_args_list]
    assert any("queued_for_morning" in c for c in calls)


@pytest.mark.asyncio
async def test_dedup_blocks_send_after_llm():
    """Dedup blocks → LLM called but send never called."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(dedup_duplicate=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(adapter=adapter, guardrails=guardrails, humanizer=humanizer)

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.invoke_llm.assert_called_once()
    adapter.send.assert_not_called()
    guardrails.dedup.is_duplicate.assert_called_once()
    guardrails.volume.exceeded.assert_not_called()


@pytest.mark.asyncio
async def test_volume_cap_blocks_send_after_llm():
    """Volume cap exceeded → LLM called but send never called."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(volume_exceeded=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(adapter=adapter, guardrails=guardrails, humanizer=humanizer)

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.invoke_llm.assert_called_once()
    adapter.send.assert_not_called()
    calls = [str(c) for c in mock_append.call_args_list]
    assert any("volume_cap" in c for c in calls)


@pytest.mark.asyncio
async def test_bounded_queue_overflow():
    """6th event dropped when queue full (max 5)."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails()
    adapter = AsyncMock()
    event_hold = asyncio.Event()

    async def slow_llm(event: dict[str, object]) -> str:
        _ = event
        await event_hold.wait()
        return "reply"

    adapter.invoke_llm = slow_llm
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(adapter=adapter, guardrails=guardrails, humanizer=humanizer)

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        for i in range(5):
            await loop.on_inbound(make_event(thread_id=f"t{i}"))
        await asyncio.sleep(0.05)
        await loop.on_inbound(make_event(thread_id="t_overflow"))
        await asyncio.sleep(0.05)
        calls = [str(c) for c in mock_append.call_args_list]
        assert any("inbound_dropped_overflow" in c for c in calls)
        _ = event_hold.set()
        await loop.stop()

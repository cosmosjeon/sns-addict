"""Tests for sns_addict.loops.inbound.InboundLoop."""

# pyright: reportAny=false, reportUnusedCallResult=false

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

from sns_addict.persistence.allowlist import Allowlist, AllowlistStore, Friend
from sns_addict.persistence.state import RuntimeMode, State, StateStore


def make_event(
    thread_id: str = "t1",
    text: str = "안녕",
    ts: float | None = None,
    **extra: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "thread_id": thread_id,
        "text": text,
        "ts": ts or time.time(),
        "message_id": "m1",
    }
    event.update(extra)
    return event


def make_guardrails(
    canary_matches: bool = False,
    quiet_active: bool = False,
    loop_frozen: bool = False,
    dedup_duplicate: bool = False,
    volume_exceeded: bool = False,
):
    from sns_addict.loops.inbound import GuardrailsBundle

    canary = MagicMock()
    canary.CANONICAL_REPLY = "뭐래 ㅋㅋ"
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
    volume.exceeded = AsyncMock(return_value=volume_exceeded)
    volume.record = AsyncMock()

    return GuardrailsBundle(
        canary=canary,
        quiet_hours=quiet,
        loop_detector=loop_det,
        dedup=dedup,
        volume=volume,
    )


async def make_state_store(tmp_path: Path, runtime_mode: RuntimeMode) -> StateStore:
    store = StateStore(tmp_path / "state.json")
    session_state = "stopped" if runtime_mode == "stopped" else "active"
    await store.write(State(session_state=session_state, runtime_mode=runtime_mode))
    return store


async def make_allowlist_store(tmp_path: Path, friends: list[str] | None = None) -> AllowlistStore:
    store = AllowlistStore(tmp_path / "allowlist.json")
    await store.write(Allowlist(friends=[Friend(username=f) for f in (friends or [])]))
    return store


@pytest.mark.asyncio
async def test_canary_first_short_circuit_in_send_capable_mode(tmp_path: Path):
    """Canary match in autopilot-lite → LLM/dedup/volume never called."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(canary_matches=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "autopilot_lite"),
        allowlist_store=await make_allowlist_store(tmp_path, ["friend-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(
            make_event(
                thread_id="thread-1",
                text="are you human",
                chat_type="dm",
                username="friend-1",
            )
        )
        await asyncio.sleep(0.1)

    guardrails.canary.handle.assert_called_once()
    adapter.invoke_llm.assert_not_called()
    adapter.send.assert_not_called()
    guardrails.dedup.is_duplicate.assert_not_called()
    guardrails.volume.exceeded.assert_not_called()


@pytest.mark.asyncio
async def test_quiet_hours_drops_event(tmp_path: Path):
    """Quiet hours active → reply never sent."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(quiet_active=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "approval"),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    adapter.invoke_llm.assert_not_called()
    calls = [str(c) for c in mock_append.call_args_list]
    assert any("queued_for_morning" in c for c in calls)


@pytest.mark.asyncio
async def test_dedup_blocks_send_after_llm(tmp_path: Path):
    """Dedup blocks → LLM called but send never called."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(dedup_duplicate=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "approval"),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.invoke_llm.assert_called_once()
    adapter.send.assert_not_called()
    guardrails.dedup.is_duplicate.assert_called_once()
    guardrails.volume.exceeded.assert_not_called()


@pytest.mark.asyncio
async def test_volume_cap_blocks_send_after_llm(tmp_path: Path):
    """Volume cap exceeded → LLM called but send never called."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails(volume_exceeded=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "approval"),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.invoke_llm.assert_called_once()
    adapter.send.assert_not_called()
    calls = [str(c) for c in mock_append.call_args_list]
    assert any("volume_cap" in c for c in calls)


@pytest.mark.asyncio
async def test_observe_mode_logs_without_llm_or_send(tmp_path: Path):
    """Observe mode records inbound visibility but never creates replies."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "observe"),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(make_event())
        await asyncio.sleep(0.1)

    adapter.invoke_llm.assert_not_called()
    adapter.send.assert_not_called()
    assert any("inbound_observed" in str(c) for c in mock_append.call_args_list)


@pytest.mark.asyncio
async def test_approval_mode_queues_proposal_without_send(tmp_path: Path):
    """Approval mode stores a proposed reply and waits for explicit approval."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "approval")
    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="queued reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(make_event(thread_id="friend-1", text="hi"))
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    state = await state_store.read()
    assert len(state.pending_sends) == 1
    assert state.pending_sends[0]["status"] == "proposed"
    assert state.pending_sends[0]["proposed_reply"] == "queued reply"


@pytest.mark.asyncio
async def test_approval_mode_canary_queues_without_send(tmp_path: Path):
    """Identity canary must not bypass approval mode with a direct send."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "approval")
    guardrails = make_guardrails(canary_matches=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="should not be used")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(make_event(thread_id="friend-1", text="너 ai야?"))
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    adapter.invoke_llm.assert_not_called()
    guardrails.canary.handle.assert_not_called()
    state = await state_store.read()
    assert state.pending_sends[0]["status"] == "proposed"
    assert state.pending_sends[0]["proposed_reply"] == "뭐래 ㅋㅋ"


@pytest.mark.asyncio
async def test_autopilot_lite_sends_only_allowlisted_one_on_one(tmp_path: Path):
    """Autopilot-lite can send automatically to allowlisted 1:1 chats."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="auto reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "autopilot_lite"),
        allowlist_store=await make_allowlist_store(tmp_path, ["friend-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(
            make_event(
                thread_id="thread-1",
                text="hi",
                chat_type="dm",
                username="friend-1",
            )
        )
        await asyncio.sleep(0.1)

    adapter.send.assert_awaited_once_with("thread-1", "auto reply")
    guardrails.volume.record.assert_awaited_once_with("thread-1")


@pytest.mark.asyncio
async def test_autopilot_lite_unallowlisted_goes_to_queue(tmp_path: Path):
    """Autopilot-lite does not auto-send outside the allowlist."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "autopilot_lite")
    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="needs approval")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
        allowlist_store=await make_allowlist_store(tmp_path, ["friend-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(
            make_event(
                thread_id="stranger-thread",
                text="hi",
                chat_type="dm",
                username="stranger",
            )
        )
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    state = await state_store.read()
    assert state.pending_sends[0]["status"] == "proposed"
    assert state.pending_sends[0]["runtime_mode"] == "autopilot_lite"


@pytest.mark.asyncio
async def test_autopilot_lite_blocks_missing_chat_shape_and_username(tmp_path: Path):
    """Production-shaped events without 1:1/user metadata never auto-send."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "autopilot_lite")
    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="needs approval")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
        allowlist_store=await make_allowlist_store(tmp_path, ["thread-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(make_event(thread_id="thread-1", text="hi"))
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    assert any("not_one_on_one" in str(call) for call in mock_append.call_args_list)
    state = await state_store.read()
    assert state.pending_sends[0]["status"] == "proposed"


@pytest.mark.asyncio
async def test_autopilot_lite_blocks_group_even_if_username_allowlisted(tmp_path: Path):
    """Autopilot-lite requires explicit one-on-one DM metadata."""
    from sns_addict.loops.inbound import InboundLoop

    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="needs approval")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "autopilot_lite"),
        allowlist_store=await make_allowlist_store(tmp_path, ["friend-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock) as mock_append:
        await loop.on_inbound(
            make_event(
                thread_id="group-thread",
                text="hi",
                chat_type="group",
                username="friend-1",
            )
        )
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    assert any("not_one_on_one" in str(call) for call in mock_append.call_args_list)


@pytest.mark.asyncio
async def test_autopilot_lite_canary_without_metadata_queues_not_send(tmp_path: Path):
    """Canary canonical reply still obeys autopilot-lite metadata/allowlist gate."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "autopilot_lite")
    guardrails = make_guardrails(canary_matches=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="unused")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
        allowlist_store=await make_allowlist_store(tmp_path, ["friend-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(make_event(thread_id="thread-1", text="are you human"))
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    guardrails.canary.handle.assert_not_called()
    state = await state_store.read()
    assert state.pending_sends[0]["proposed_reply"] == "뭐래 ㅋㅋ"
    assert state.pending_sends[0]["runtime_mode"] == "autopilot_lite"


@pytest.mark.asyncio
async def test_autopilot_lite_canary_group_queues_not_send(tmp_path: Path):
    """Canary canonical reply must not auto-send to group threads."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "autopilot_lite")
    guardrails = make_guardrails(canary_matches=True)
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="unused")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
        allowlist_store=await make_allowlist_store(tmp_path, ["friend-1"]),
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(
            make_event(
                thread_id="group-thread",
                text="bot?",
                chat_type="group",
                username="friend-1",
            )
        )
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    guardrails.canary.handle.assert_not_called()
    state = await state_store.read()
    assert state.pending_sends[0]["proposed_reply"] == "뭐래 ㅋㅋ"


@pytest.mark.asyncio
async def test_autopilot_lite_rechecks_mode_before_send_after_llm(tmp_path: Path):
    """A mode switch during LLM generation must stop an autopilot-lite send."""
    from sns_addict.loops.inbound import InboundLoop

    state_store = await make_state_store(tmp_path, "autopilot_lite")
    allowlist_store = await make_allowlist_store(tmp_path, ["friend-1"])
    guardrails = make_guardrails()
    adapter = AsyncMock()
    started = asyncio.Event()
    resume = asyncio.Event()

    async def invoke_llm(_event: object) -> str:
        started.set()
        await resume.wait()
        return "auto reply"

    adapter.invoke_llm = invoke_llm
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
        allowlist_store=allowlist_store,
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(
            make_event(
                thread_id="thread-1",
                text="hi",
                chat_type="dm",
                username="friend-1",
            )
        )
        await started.wait()
        await state_store.write(State(session_state="active", runtime_mode="observe"))
        resume.set()
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    state = await state_store.read()
    assert state.pending_sends == []
    guardrails.volume.record.assert_not_called()


@pytest.mark.asyncio
async def test_autopilot_lite_rechecks_mode_after_allowlist_before_send(tmp_path: Path):
    """A mode switch during allowlist lookup must stop the direct send."""
    from sns_addict.loops.inbound import InboundLoop

    class SlowAllowlistStore:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.resume = asyncio.Event()

        async def read(self) -> Allowlist:
            self.started.set()
            await self.resume.wait()
            return Allowlist(friends=[Friend(username="friend-1")])

    state_store = await make_state_store(tmp_path, "autopilot_lite")
    allowlist_store = SlowAllowlistStore()
    guardrails = make_guardrails()
    adapter = AsyncMock()
    adapter.invoke_llm = AsyncMock(return_value="auto reply")
    adapter.send = AsyncMock()
    humanizer = MagicMock()
    humanizer.next_pause = MagicMock(return_value=0)
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=state_store,
        allowlist_store=allowlist_store,
    )

    with patch("sns_addict.loops.inbound.append_event", new_callable=AsyncMock):
        await loop.on_inbound(
            make_event(
                thread_id="thread-1",
                text="hi",
                chat_type="dm",
                username="friend-1",
            )
        )
        await allowlist_store.started.wait()
        await state_store.write(State(session_state="active", runtime_mode="observe"))
        allowlist_store.resume.set()
        await asyncio.sleep(0.1)

    adapter.send.assert_not_called()
    state = await state_store.read()
    assert state.pending_sends == []
    guardrails.volume.record.assert_not_called()


@pytest.mark.asyncio
async def test_bounded_queue_overflow(tmp_path: Path):
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
    loop = InboundLoop(
        adapter=adapter,
        guardrails=guardrails,
        humanizer=humanizer,
        state_store=await make_state_store(tmp_path, "approval"),
    )

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

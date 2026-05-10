"""Inbound Loop A — master orchestrator for all inbound DM processing.

Pipeline (canary ALWAYS first):
  1. canary      → identity check, halt on hit
  2. quiet       → quiet hours gate
  3. loop_detector → frozen thread gate
  4. LLM         → invoke_llm (returns string, no auto-send)
  5. dedup       → duplicate reply gate
  6. volume      → volume cap gate
  7. send        → adapter.send (fire-and-best-effort)

Bounded queue: max 5 concurrent tasks. Overflow → drop + log.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sns_addict.persistence.events import append_event
from sns_addict.persistence.allowlist import AllowlistStore
from sns_addict.persistence.state import RuntimeMode, StateStore

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 5
_STOP_DRAIN_TIMEOUT = 10.0


@dataclass
class GuardrailsBundle:
    """Container for all guardrail instances passed to InboundLoop."""

    canary: Any
    quiet_hours: Any
    loop_detector: Any
    dedup: Any
    volume: Any


class InboundLoop:
    """Master orchestrator for inbound DM events.

    Usage::

        bundle = GuardrailsBundle(canary=..., quiet_hours=..., ...)
        loop = InboundLoop(adapter=adapter, guardrails=bundle, humanizer=humanizer)
        adapter.set_inbound_loop(loop)
        # ... later ...
        await loop.on_inbound(event_dict)
        # ... on shutdown ...
        await loop.stop()
    """

    def __init__(
        self,
        adapter: Any,
        guardrails: GuardrailsBundle,
        humanizer: Any,
        state_store: StateStore | None = None,
        allowlist_store: AllowlistStore | None = None,
    ) -> None:
        self._adapter = adapter
        self._guardrails = guardrails
        self._humanizer = humanizer
        self._state_store = state_store if state_store is not None else StateStore()
        self._allowlist_store = (
            allowlist_store if allowlist_store is not None else AllowlistStore()
        )
        self._inbound_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def on_inbound(self, event: dict[str, Any]) -> None:
        """Receive an inbound event and schedule pipeline execution.

        Returns immediately (< 1 ms). Drops event if queue is full.
        """
        if self._stopping:
            logger.debug("InboundLoop stopping — dropping event for %s", event.get("thread_id"))
            return

        if len(self._inbound_tasks) >= _MAX_CONCURRENT:
            logger.warning(
                "InboundLoop queue full (%d/%d) — dropping event for %s",
                len(self._inbound_tasks),
                _MAX_CONCURRENT,
                event.get("thread_id"),
            )
            await append_event(
                "inbound_dropped_overflow",
                thread_id=event.get("thread_id", "unknown"),
            )
            return

        task: asyncio.Task[None] = asyncio.create_task(
            self._run_pipeline(event),
            name=f"inbound-{event.get('thread_id', 'unknown')}-{int(time.time())}",
        )
        self._inbound_tasks.add(task)
        task.add_done_callback(self._inbound_tasks.discard)

    async def stop(self) -> None:
        """Drain in-flight tasks with a 10-second timeout, then cancel."""
        self._stopping = True
        if not self._inbound_tasks:
            return

        logger.info("InboundLoop stopping — draining %d in-flight tasks", len(self._inbound_tasks))
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(self._inbound_tasks), return_exceptions=True),
                timeout=_STOP_DRAIN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("InboundLoop drain timed out — cancelling remaining tasks")
            for task in list(self._inbound_tasks):
                task.cancel()
            await asyncio.gather(*list(self._inbound_tasks), return_exceptions=True)

        logger.info("InboundLoop stopped")

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(self, event: dict[str, Any]) -> None:
        """Execute the 7-step guardrail pipeline for one inbound event."""
        thread_id: str = event.get("thread_id", "unknown")
        text: str = event.get("text", "")
        ts: float = event.get("ts", time.time())

        try:
            runtime_mode = await self._runtime_mode()
            if runtime_mode == "stopped":
                await append_event(
                    "inbound_ignored_runtime_mode",
                    runtime_mode=runtime_mode,
                    thread_id_hash=_hash_thread(thread_id),
                    text=text,
                )
                return

            if runtime_mode == "observe":
                await append_event(
                    "inbound_observed",
                    runtime_mode=runtime_mode,
                    thread_id_hash=_hash_thread(thread_id),
                    text=text,
                )
                return

            # Step 1 — identity canary (first for send-capable modes only).
            if self._guardrails.canary.matches(text):
                logger.warning("Identity canary hit for thread %s", thread_id)
                canonical_reply = str(
                    getattr(self._guardrails.canary, "CANONICAL_REPLY", "뭐래 ㅋㅋ")
                )
                if runtime_mode == "approval":
                    if not await self._allowlisted_one_on_one(event):
                        await append_event(
                            "inbound_blocked_not_allowlisted",
                            thread_id_hash=_hash_thread(thread_id),
                        )
                        return
                    await self._enqueue_proposal(event, canonical_reply, runtime_mode)
                    await append_event(
                        "identity_canary_proposed",
                        thread_id_hash=_hash_thread(thread_id),
                    )
                    return
                if runtime_mode == "autopilot_lite" and not await self._autopilot_allowed(event):
                    await append_event(
                        "identity_canary_autopilot_blocked",
                        thread_id_hash=_hash_thread(thread_id),
                    )
                    return
                latest_mode = await self._runtime_mode()
                if latest_mode != "autopilot_lite":
                    if latest_mode == "approval":
                        if await self._allowlisted_one_on_one(event):
                            await self._enqueue_proposal(event, canonical_reply, latest_mode)
                            await append_event(
                                "identity_canary_proposed",
                                thread_id_hash=_hash_thread(thread_id),
                            )
                        else:
                            await append_event(
                                "inbound_blocked_not_allowlisted",
                                thread_id_hash=_hash_thread(thread_id),
                            )
                    else:
                        await append_event(
                            "inbound_ignored_runtime_mode",
                            runtime_mode=latest_mode,
                            thread_id_hash=_hash_thread(thread_id),
                            text=text,
                        )
                    return
                await self._guardrails.canary.handle(
                    SimpleNamespace(thread_id=thread_id),
                    self._adapter,
                )
                return

            # Step 1.5 — allowlist gate before any draft or send.
            if not await self._allowlisted_one_on_one(event):
                await append_event(
                    "inbound_blocked_not_allowlisted",
                    thread_id_hash=_hash_thread(thread_id),
                )
                return

            # Step 2 — quiet hours
            if self._guardrails.quiet_hours.is_active():
                logger.info("Quiet hours active — dropping event for %s", thread_id)
                await append_event("queued_for_morning", thread_id_hash=_hash_thread(thread_id))
                return

            # Step 3 — loop detector
            if self._guardrails.loop_detector.is_frozen(thread_id):
                logger.info("Thread %s is frozen by loop detector — dropping", thread_id)
                await append_event("guard_block", reason="loop_detector", thread_id_hash=_hash_thread(thread_id))
                return

            # Step 4 — LLM (thinking pause + invoke). In approval mode, an
            # unavailable auxiliary LLM should still prove that the inbound DM
            # was detected by surfacing a non-sendable diagnostic proposal.
            thinking_delay = self._humanizer.next_pause("thinking")
            await asyncio.sleep(thinking_delay)
            try:
                reply: str = await self._adapter.invoke_llm(event)
            except Exception as exc:  # noqa: BLE001
                await append_event(
                    "llm_draft_failed",
                    thread_id_hash=_hash_thread(thread_id),
                    error=str(exc)[:200],
                )
                latest_mode = await self._runtime_mode()
                if latest_mode == "approval":
                    await self._enqueue_proposal(
                        event,
                        "[LLM unavailable — inbound DM detected, but draft generation failed. "
                        "Check Hermes auxiliary LLM auth/config before approving replies.]",
                        latest_mode,
                    )
                return

            if not reply:
                logger.warning("LLM returned empty reply for thread %s — skipping send", thread_id)
                await append_event("llm_empty_reply", thread_id_hash=_hash_thread(thread_id))
                return

            # Step 5 — dedup
            if self._guardrails.dedup.is_duplicate(thread_id, reply):
                logger.info("Dedup blocked reply for thread %s", thread_id)
                await append_event("guard_block", reason="dedup", thread_id_hash=_hash_thread(thread_id))
                return

            # Step 6 — volume cap
            if await self._guardrails.volume.exceeded(thread_id):
                logger.info("Volume cap exceeded for thread %s", thread_id)
                await append_event("guard_block", reason="volume_cap", thread_id_hash=_hash_thread(thread_id))
                return

            # Step 7 — send or queue depending on the latest runtime mode.
            # Re-read immediately before any side effect; the user may have switched
            # to observe/stopped while thinking or LLM generation was in flight.
            latest_mode = await self._runtime_mode()
            if latest_mode == "approval":
                await self._enqueue_proposal(event, reply, latest_mode)
                return

            if latest_mode == "autopilot_lite":
                allowed = await self._autopilot_allowed(event)
                if not allowed:
                    return
                latest_mode = await self._runtime_mode()
                if latest_mode != "autopilot_lite":
                    if latest_mode == "approval":
                        if await self._allowlisted_one_on_one(event):
                            await self._enqueue_proposal(event, reply, latest_mode)
                        else:
                            await append_event(
                                "inbound_blocked_not_allowlisted",
                                thread_id_hash=_hash_thread(thread_id),
                            )
                    else:
                        await append_event(
                            "inbound_ignored_runtime_mode",
                            runtime_mode=latest_mode,
                            thread_id_hash=_hash_thread(thread_id),
                            text=text,
                        )
                    return
                await self._adapter.send(thread_id, reply)
            else:
                await append_event(
                    "inbound_ignored_runtime_mode",
                    runtime_mode=latest_mode,
                    thread_id_hash=_hash_thread(thread_id),
                    text=text,
                )
                return

            # Post-send bookkeeping
            await self._guardrails.volume.record(thread_id)
            self._guardrails.dedup.record(thread_id, reply)
            self._guardrails.loop_detector.record_turn(thread_id)

            latency_ms = int((time.time() - ts) * 1000)
            thread_id_hash = hashlib.sha256(thread_id.encode()).hexdigest()[:16]
            await append_event(
                "reply_sent",
                latency_ms=latency_ms,
                thread_id_hash=thread_id_hash,
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("InboundLoop pipeline error for thread %s: %s", thread_id, exc)
            await append_event(
                "guard_block",
                reason="pipeline_error",
                thread_id_hash=_hash_thread(thread_id),
                error=str(exc),
            )

    async def _runtime_mode(self) -> RuntimeMode:
        state = await self._state_store.read()
        if state.session_state in ("stopped", "halted", "challenge_pending"):
            return "stopped"
        return state.runtime_mode

    async def _autopilot_allowed(self, event: dict[str, Any]) -> bool:
        return await self._allowlisted_one_on_one(
            event,
            event_name="autopilot_lite_blocked",
        )

    async def _allowlisted_one_on_one(
        self,
        event: dict[str, Any],
        *,
        event_name: str = "allowlist_blocked",
    ) -> bool:
        thread_id = str(event.get("thread_id") or "")
        if not thread_id:
            return False

        chat_type_raw = event.get("chat_type") or event.get("type")
        chat_type = str(chat_type_raw or "").lower()
        is_group = bool(event.get("is_group")) or chat_type in {"group", "group_dm"}
        if is_group or chat_type != "dm":
            await append_event(
                event_name,
                reason="not_one_on_one",
                thread_id_hash=_hash_thread(thread_id),
            )
            return False

        username = _event_username(event)
        if not username:
            await append_event(
                event_name,
                reason="missing_username",
                thread_id_hash=_hash_thread(thread_id),
            )
            return False

        allowlist = await self._allowlist_store.read()
        usernames = {_normalize_username(friend.username) for friend in allowlist.friends}
        if _normalize_username(username) not in usernames:
            await append_event(
                event_name,
                reason="not_allowlisted",
                thread_id_hash=_hash_thread(thread_id),
            )
            return False

        return True

    async def _enqueue_proposal(
        self,
        event: dict[str, Any],
        reply: str,
        runtime_mode: RuntimeMode,
    ) -> None:
        thread_id = str(event.get("thread_id") or "unknown")
        message_id = str(event.get("message_id") or "")
        proposal_id = _proposal_id(thread_id, message_id, reply)
        now = time.time()

        async def _add_proposal(state: Any) -> Any:
            for item in state.pending_sends:
                if item.get("id") == proposal_id:
                    return state
            state.pending_sends.append(
                {
                    "id": proposal_id,
                    "status": "proposed",
                    "source": "inbound",
                    "thread_id": thread_id,
                    "thread_id_hash": _hash_thread(thread_id),
                    "message_id": message_id,
                    "inbound_text_hash": _hash_text(str(event.get("text") or "")),
                    "proposed_reply": reply,
                    "runtime_mode": runtime_mode,
                    "queued_at": now,
                }
            )
            return state

        await self._state_store.update(_add_proposal)
        await append_event(
            "reply_proposed",
            proposal_id=proposal_id,
            runtime_mode=runtime_mode,
            thread_id_hash=_hash_thread(thread_id),
        )


def _event_username(event: dict[str, Any]) -> str:
    """Extract the Instagram username shape used by the allowlist UI."""
    for key in ("username", "sender_username", "participant_username", "from_username"):
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_username(username: str) -> str:
    return username.strip().lstrip("@").lower()


def _hash_thread(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _proposal_id(thread_id: str, message_id: str, reply: str) -> str:
    return hashlib.sha256(
        f"{thread_id}:{message_id}:{reply}".encode("utf-8")
    ).hexdigest()[:16]

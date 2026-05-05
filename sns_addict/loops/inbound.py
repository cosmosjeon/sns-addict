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
from dataclasses import dataclass, field
from typing import Any

from sns_addict.persistence.events import append_event

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

    def __init__(self, adapter: Any, guardrails: GuardrailsBundle, humanizer: Any) -> None:
        self._adapter = adapter
        self._guardrails = guardrails
        self._humanizer = humanizer
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
            # Step 1 — identity canary (ALWAYS FIRST)
            if self._guardrails.canary.matches(text):
                logger.warning("Identity canary hit for thread %s", thread_id)
                await self._guardrails.canary.handle(event, self._adapter)
                return

            # Step 2 — quiet hours
            if self._guardrails.quiet_hours.is_active():
                logger.info("Quiet hours active — dropping event for %s", thread_id)
                await append_event("queued_for_morning", thread_id=thread_id)
                return

            # Step 3 — loop detector
            if self._guardrails.loop_detector.is_frozen(thread_id):
                logger.info("Thread %s is frozen by loop detector — dropping", thread_id)
                return

            # Step 4 — LLM (thinking pause + invoke)
            thinking_delay = self._humanizer.next_pause("thinking")
            await asyncio.sleep(thinking_delay)
            reply: str = await self._adapter.invoke_llm(event)

            if not reply:
                logger.warning("LLM returned empty reply for thread %s — skipping send", thread_id)
                return

            # Step 5 — dedup
            if self._guardrails.dedup.is_duplicate(thread_id, reply):
                logger.info("Dedup blocked reply for thread %s", thread_id)
                await append_event("guard_block", reason="dedup", thread_id=thread_id)
                return

            # Step 6 — volume cap
            if self._guardrails.volume.exceeded(thread_id):
                logger.info("Volume cap exceeded for thread %s", thread_id)
                await append_event("guard_block", reason="volume_cap", thread_id=thread_id)
                return

            # Step 7 — send
            await self._adapter.send(thread_id, reply)

            # Post-send bookkeeping
            self._guardrails.volume.record(thread_id)
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
                thread_id=thread_id,
                error=str(exc),
            )

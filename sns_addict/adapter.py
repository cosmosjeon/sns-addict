"""SnsAddictAdapter — Hermes BasePlatformAdapter implementation for Instagram.

InboundLoop is the master orchestrator (``handle_message`` is never called).
Only ``invoke_llm`` (openai_direct + SOUL.md) and ``send`` (BasePlatformAdapter
standard) are exposed to it. ``send`` is fire-and-best-effort (no retry —
duplicate-DM risk).

DOM Observer fires → ``_on_dom_event`` returns < 50 ms by spawning a task →
``_process_inbound`` reads thread context → dispatches to InboundLoop.

State watcher polls ``state.json`` every 5 s (dashboard ↔ adapter IPC):
``active``/safe runtime modes → ``connect()`` ; ``stopped``/``halted`` → ``disconnect()``.

``f3_mode`` defaults to False (privacy). When True, plaintext replies are
appended to ``replies-f3.jsonl`` (voice_score.py compatible).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


try:
    from gateway.platforms.base import (  # pyright: ignore[reportMissingImports]
        BasePlatformAdapter,
        SendResult,
    )
    from gateway.config import (  # pyright: ignore[reportMissingImports]
        Platform,
        PlatformConfig,
    )

    _hermes_available = True
except ImportError:
    # Dev/test fallback so the module imports without Hermes on the path.
    # Field shapes mirror the real Hermes types so issubclass/hasattr behave
    # identically; production import path takes precedence whenever available.
    _hermes_available = False

    @dataclass
    class SendResult:  # pyright: ignore[reportGeneralTypeIssues]
        success: bool
        message_id: Optional[str] = None
        error: Optional[str] = None
        raw_response: Any = None
        retryable: bool = False

    @dataclass
    class PlatformConfig:  # pyright: ignore[reportGeneralTypeIssues]
        enabled: bool = False
        token: Optional[str] = None
        api_key: Optional[str] = None
        extra: dict[str, Any] = field(default_factory=dict)

    class Platform:  # pyright: ignore[reportGeneralTypeIssues]
        value: str

        def __init__(self, value: str) -> None:
            self.value = value

        @property
        def name(self) -> str:
            return self.value.upper()

    class BasePlatformAdapter:  # pyright: ignore[reportGeneralTypeIssues]
        config: Any
        platform: Any
        _running: bool
        _background_tasks: set[asyncio.Task[Any]]
        _message_handler: Any

        def __init__(
            self,
            config: PlatformConfig,
            platform: Platform,
        ) -> None:
            self.config = config
            self.platform = platform
            self._running = False
            self._background_tasks = set()
            self._message_handler = None

        @property
        def is_connected(self) -> bool:
            return self._running

        def _mark_connected(self) -> None:
            self._running = True

        def _mark_disconnected(self) -> None:
            self._running = False


try:
    from agent.auxiliary_client import (  # pyright: ignore[reportMissingImports]
        get_async_text_auxiliary_client,
    )

    _hermes_auxiliary_available = True
except ImportError:
    # Dev/test fallback: keep the symbol importable at module level so that
    # ``sns_addict.adapter.get_async_text_auxiliary_client`` can be patched in
    # tests, and so ``invoke_llm`` raises a clear RuntimeError rather than
    # NameError when Hermes-auth is not on PYTHONPATH.
    _hermes_auxiliary_available = False

    def get_async_text_auxiliary_client(  # type: ignore[misc]
        task: str = "",
        **_kwargs: Any,
    ) -> tuple[Any, Any]:
        return (None, None)


from sns_addict.browser.session import BrowserSession  # noqa: E402
from sns_addict.detection.dom_observer import inject_dom_observer  # noqa: E402
from sns_addict.guardrails.halt_now import HaltNow, watch_soul_md  # noqa: E402
from sns_addict.llm_backend import resolve_llm_backend  # noqa: E402
from sns_addict.persistence.events import append_event  # noqa: E402
from sns_addict.persistence.state import State, StateStore  # noqa: E402
from sns_addict.utils.long_run import AutoStop, SleepRecovery  # noqa: E402

STATE_STORE = StateStore()
REPLIES_F3_PATH = Path.home() / ".hermes" / "sns-addict" / "logs" / "replies-f3.jsonl"


def _resolve_platform() -> Platform:
    try:
        return Platform("sns_addict")
    except (ValueError, KeyError):
        return Platform("local")


def _f3_mode_enabled(cfg: Any) -> bool:
    if cfg is None:
        return False
    extra = getattr(cfg, "extra", None)
    if isinstance(extra, dict) and "f3_mode" in extra:
        return bool(extra["f3_mode"])
    return bool(getattr(cfg, "f3_mode", False))


def _hash_thread(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class SnsAddictAdapter(BasePlatformAdapter):  # pyright: ignore[reportGeneralTypeIssues, reportUntypedBaseClass]
    """Instagram DM bot adapter using Patchright browser automation.

    Implements four abstract methods (``connect``, ``disconnect``, ``send``,
    ``get_chat_info``) plus sns-addict helpers ``invoke_llm`` (openai_direct
    path) and ``_watch_state`` (state.json IPC watcher). InboundLoop (W3.2)
    is wired via ``set_inbound_loop``.
    """

    def __init__(
        self,
        config: PlatformConfig,
        platform: Optional[Platform] = None,
        state_store: StateStore | None = None,
    ) -> None:
        super().__init__(config, platform if platform is not None else _resolve_platform())
        self._state_store = state_store if state_store is not None else STATE_STORE
        self._session: Optional[BrowserSession] = None
        self._inbound_loop: Any = None
        self._halt_task: Optional[asyncio.Task[None]] = None
        self._refresh_task: Optional[asyncio.Task[None]] = None
        self._soul_task: Optional[asyncio.Task[None]] = None
        self._state_watcher_task: Optional[asyncio.Task[None]] = None
        self._approval_sender_task: Optional[asyncio.Task[None]] = None
        self._inbox_poll_task: Optional[asyncio.Task[None]] = None
        self._auto_stop_task: Optional[asyncio.Task[None]] = None
        self._sleep_recovery_task: Optional[asyncio.Task[None]] = None
        self._inbox_snapshot: dict[str, str] = {}
        self._thread_last_inbound_snapshot: dict[str, str] = {}
        self._browser_action_lock = asyncio.Lock()

    def set_inbound_loop(self, inbound_loop: Any) -> None:
        """Wire the InboundLoop master orchestrator (W3.2)."""
        self._inbound_loop = inbound_loop

    async def connect(self) -> bool:
        """Idempotent connect: start browser, inject DOM observer, spawn watchers."""
        if self.is_connected:
            return True
        profile_dir = Path.home() / ".hermes" / "sns-addict" / "profile"
        singleton_lock = profile_dir / "SingletonLock"
        if singleton_lock.exists():
            singleton_lock.unlink()
            logger.warning(
                "cleared_stale_singleton_lock",
                extra={"path": str(singleton_lock)},
            )
        self._session = BrowserSession(profile_dir=profile_dir)
        page = await self._session.start()
        try:
            await append_event("adapter_browser_started", url=str(page.url)[:200])
        except Exception:
            pass
        goto_ok = False
        try:
            await page.goto(
                "https://www.instagram.com/direct/inbox/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            goto_ok = True
        except Exception as exc:
            logger.warning("IG inbox navigation failed: %s", exc)
            try:
                await append_event("adapter_goto_failed", error=str(exc)[:200])
            except Exception:
                pass
        try:
            await append_event(
                "adapter_after_goto",
                url=str(page.url)[:200],
                goto_ok=goto_ok,
            )
        except Exception:
            pass
        if "instagram.com/accounts/login" in str(page.url):
            try:
                await append_event("adapter_login_required", url=str(page.url)[:200])
            except Exception:
                pass
            try:
                await self._session.stop()
            finally:
                self._session = None
            return False
        try:
            await inject_dom_observer(page, self._on_dom_event)
            try:
                await append_event("adapter_observer_injected", url=str(page.url)[:200])
            except Exception:
                pass
        except Exception as exc:
            logger.warning("DOM Observer injection failed: %s", exc)
            try:
                await append_event("adapter_observer_inject_failed", error=str(exc)[:200])
            except Exception:
                pass

        # Keep Chromium on the inbox list. Older builds auto-clicked the first
        # thread here, which made new-message detection look broken because the
        # observer was watching one conversation instead of the inbox.
        await append_event("inbox_watch_ready", url=str(page.url)[:200])
        self._halt_task = asyncio.create_task(HaltNow().watch(self))
        self._soul_task = asyncio.create_task(watch_soul_md())
        self._auto_stop_task = asyncio.create_task(AutoStop(self).watch())
        self._sleep_recovery_task = asyncio.create_task(SleepRecovery(self).watch())
        self._approval_sender_task = asyncio.create_task(self._watch_approved_sends())
        self._inbox_poll_task = asyncio.create_task(self._watch_inbox_changes())
        await self._state_store.update(_set_session_active)
        self._mark_connected()
        logger.info("SnsAddictAdapter connected")
        return True

    async def disconnect(self) -> None:
        """Idempotent disconnect: stop browser, drain InboundLoop, cancel watchers."""
        if not self.is_connected and self._session is None:
            return
        self._mark_disconnected()
        for task in (
            self._halt_task,
            self._soul_task,
            self._auto_stop_task,
            self._sleep_recovery_task,
            self._approval_sender_task,
            self._inbox_poll_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        if self._inbound_loop is not None:
            try:
                stop = getattr(self._inbound_loop, "stop", None)
                if stop is not None:
                    await stop()
            except Exception as exc:
                logger.debug("InboundLoop stop error (ignored): %s", exc)
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception as exc:
                logger.debug("BrowserSession stop error (ignored): %s", exc)
            self._session = None
        await self._state_store.update(_set_session_stopped)
        logger.info("SnsAddictAdapter disconnected")

    async def _watch_approved_sends(self) -> None:
        """Poll approval queue and dispatch user-approved replies only."""
        while True:
            await asyncio.sleep(2)
            try:
                state = await self._state_store.read()
                if state.session_state != "active" or state.runtime_mode not in {
                    "approval",
                    "autopilot_lite",
                }:
                    continue
                item = await self._claim_approved_send()
                if item is None:
                    continue
                proposal_id = str(item.get("id") or "")
                thread_id = str(item.get("thread_id") or "")
                proposed_reply = str(item.get("proposed_reply") or "")
                if not thread_id or not proposed_reply:
                    await self._complete_approved_send(
                        proposal_id,
                        SendResult(
                            success=False,
                            error="approved proposal missing thread_id or proposed_reply",
                            retryable=False,
                        ),
                    )
                    continue
                state = await self._state_store.read()
                if state.session_state != "active" or state.runtime_mode not in {
                    "approval",
                    "autopilot_lite",
                }:
                    await self._restore_approved_send(proposal_id)
                    continue
                result = await self.send(thread_id, proposed_reply)
                await self._complete_approved_send(proposal_id, result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("approved send watcher error: %s", exc)


    async def _watch_inbox_changes(self) -> None:
        """Poll the Instagram inbox as a fallback to DOM observer callbacks.

        Instagram DOM/aria labels drift often. This watcher compares the inbox
        thread list snapshot and emits inbound events when a thread row changes
        or exposes an unread hint. It keeps the MVP observable even when the
        injected observer misses React updates.
        """
        while True:
            await asyncio.sleep(3)
            try:
                state = await self._state_store.read()
                if state.session_state != "active" or state.runtime_mode == "stopped":
                    continue
                if self._session is None or self._session.page is None:
                    continue
                from sns_addict.actions.dm import DMActions
                from sns_addict.actions.humanize import Humanizer

                dma = DMActions(self._session.page, Humanizer())
                async with self._browser_action_lock:
                    threads = await dma.list_inbox_threads()
                if not threads:
                    await append_event("inbox_poll_empty")
                    continue
                changed = 0
                next_snapshot: dict[str, str] = {}
                for row_index, thread in enumerate(threads[:20]):
                    href = str(thread.get("href") or "")
                    row_text = str(thread.get("text") or thread.get("title") or "")
                    thread_key = _inbox_thread_key(row_index, thread)
                    if not thread_key:
                        continue
                    signature = _hash_text(row_text)
                    prev = self._inbox_snapshot.get(thread_key)
                    next_snapshot[thread_key] = signature
                    if not self._inbox_snapshot:
                        continue
                    # Row-level signals are still useful when Instagram exposes
                    # unread/text changes. A separate top-thread scan below handles
                    # static rows by actually reading recent thread contents.
                    if bool(thread.get("unread")) or (prev is not None and prev != signature):
                        changed += 1
                        await append_event(
                            "inbox_poll_inbound_likely",
                            thread_id_hash=_hash_thread(thread_key),
                            preview_hash=_hash_text(row_text),
                            unread=bool(thread.get("unread")),
                            href_resolved=bool(href),
                            row_index=row_index,
                        )
                        if not href:
                            async with self._browser_action_lock:
                                href = await dma.resolve_inbox_thread_href(row_index)
                            if "/direct/t/" not in href:
                                await append_event(
                                    "inbox_poll_unresolved_thread_href",
                                    row_index=row_index,
                                    preview_hash=_hash_text(row_text),
                                )
                                continue
                            await append_event(
                                "inbox_poll_thread_href_resolved_by_click",
                                row_index=row_index,
                                thread_id_hash=_hash_thread(
                                    href.split("/direct/t/")[-1].rstrip("/")
                                ),
                            )
                        thread_id = _thread_id_from_href(href)
                        if not thread_id:
                            continue
                        async with self._browser_action_lock:
                            await self._dispatch_thread_if_new_inbound(
                                dma,
                                thread_id,
                                source="inbox_poll",
                            )

                        # Return the browser to the inbox so subsequent polls keep
                        # watching the list instead of staying inside one thread.
                        try:
                            async with self._browser_action_lock:
                                await self._session.page.goto(  # type: ignore[union-attr]
                                    "https://www.instagram.com/direct/inbox/",
                                    wait_until="domcontentloaded",
                                    timeout=30000,
                                )
                        except Exception as exc:  # noqa: BLE001
                            await append_event(
                                "inbox_poll_return_to_inbox_failed",
                                error=str(exc)[:200],
                            )
                if next_snapshot:
                    # Do not let the active top-thread scan starve newly-opened
                    # conversations just because row text is static. The helper
                    # baselines the latest inbound message first, then dispatches
                    # only when it changes.
                    for row_index, thread in enumerate(threads[:3]):
                        href = str(thread.get("href") or "")
                        thread_id = _thread_id_from_href(href)
                        if not thread_id:
                            continue
                        async with self._browser_action_lock:
                            await self._dispatch_thread_if_new_inbound(
                                dma,
                                thread_id,
                                source="top_thread_poll",
                            )
                        try:
                            async with self._browser_action_lock:
                                await self._session.page.goto(  # type: ignore[union-attr]
                                    "https://www.instagram.com/direct/inbox/",
                                    wait_until="domcontentloaded",
                                    timeout=30000,
                                )
                        except Exception as exc:  # noqa: BLE001
                            await append_event(
                                "inbox_poll_return_to_inbox_failed",
                                error=str(exc)[:200],
                            )
                self._inbox_snapshot = next_snapshot
                await append_event(
                    "inbox_poll_heartbeat",
                    thread_count=len(next_snapshot),
                    changed=changed,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("inbox poll watcher error: %s", exc)
                try:
                    await append_event("inbox_poll_error", error=str(exc)[:200])
                except Exception:
                    pass

    async def _dispatch_thread_if_new_inbound(
        self,
        dma: Any,
        thread_id: str,
        *,
        source: str,
    ) -> bool:
        """Read one thread and dispatch only when its latest inbound changes.

        Row-level inbox signals are unreliable on Instagram. This helper is the
        actual DM-read gate used by polling: it opens/reads a thread, records the
        latest non-self message signature as a baseline, and only calls
        ``InboundLoop`` when that signature changes after the baseline.
        """
        if self._inbound_loop is None or self._session is None or self._session.page is None:
            return False
        try:
            messages = await dma.read_thread(thread_id, limit=5)
            metadata = await _read_thread_metadata(self._session.page)
        except Exception as exc:  # noqa: BLE001
            await append_event(
                "thread_poll_read_failed",
                source=source,
                thread_id_hash=_hash_thread(thread_id),
                error=str(exc)[:200],
            )
            return False
        if not messages:
            await append_event(
                "thread_poll_empty",
                source=source,
                thread_id_hash=_hash_thread(thread_id),
            )
            return False
        last = messages[-1]
        if last.get("is_self"):
            self._thread_last_inbound_snapshot.pop(thread_id, None)
            await append_event(
                "thread_poll_latest_self",
                source=source,
                thread_id_hash=_hash_thread(thread_id),
            )
            return False
        text = str(last.get("text") or "")
        if not text:
            return False
        signature = _hash_text(text)
        previous = self._thread_last_inbound_snapshot.get(thread_id)
        self._thread_last_inbound_snapshot[thread_id] = signature
        if previous is None:
            await append_event(
                "thread_poll_baselined",
                source=source,
                thread_id_hash=_hash_thread(thread_id),
            )
            return False
        if previous == signature:
            return False

        await append_event(
            "thread_poll_new_inbound",
            source=source,
            thread_id_hash=_hash_thread(thread_id),
            text_hash=signature,
        )
        await self._inbound_loop.on_inbound(
            {
                "thread_id": thread_id,
                "text": text,
                "ts": time.time(),
                "message_id": hashlib.sha256(
                    f"{thread_id}{text}".encode("utf-8")
                ).hexdigest()[:16],
                **metadata,
            }
        )
        return True

    async def _claim_approved_send(self) -> dict[str, Any] | None:
        claimed: dict[str, Any] | None = None

        async def _claim(state: State) -> State:
            nonlocal claimed
            for item in state.pending_sends:
                if item.get("status") == "approved":
                    item["status"] = "sending"
                    item["sending_at"] = time.time()
                    claimed = dict(item)
                    break
            return state

        await self._state_store.update(_claim)
        return claimed

    async def _restore_approved_send(self, proposal_id: str) -> None:
        async def _restore(state: State) -> State:
            for item in state.pending_sends:
                if item.get("id") == proposal_id and item.get("status") == "sending":
                    item["status"] = "approved"
                    item.pop("sending_at", None)
                    break
            return state

        await self._state_store.update(_restore)

    async def _complete_approved_send(self, proposal_id: str, result: SendResult) -> None:
        async def _complete(state: State) -> State:
            for item in state.pending_sends:
                if item.get("id") == proposal_id:
                    item["status"] = "sent" if result.success else "failed"
                    item["completed_at"] = time.time()
                    if result.message_id:
                        item["sent_message_id"] = result.message_id
                    if result.error:
                        item["error"] = result.error
                    if result.success:
                        _record_send_counter(state, str(item.get("thread_id") or ""))
                    break
            return state

        await self._state_store.update(_complete)
        await append_event(
            "approved_reply_sent" if result.success else "approved_reply_failed",
            proposal_id=proposal_id,
            error=result.error,
        )

    def _on_dom_event(self, event: dict[str, Any]) -> None:
        """DOM Observer callback — must return in < 50 ms (no awaits)."""
        try:
            kind = str(event.get("kind") or "")
            if kind in ("observer_alive", "observer_heartbeat", "inbound_likely"):
                asyncio.create_task(
                    append_event(
                        f"dom_{kind}",
                        thread_count=event.get("thread_count"),
                        thread_href=event.get("thread_href"),
                        preview_hash=_hash_text(str(event.get("preview") or ""))
                        if event.get("preview")
                        else None,
                    )
                )
            asyncio.create_task(self._process_inbound(event))
        except RuntimeError as exc:
            logger.warning("_on_dom_event: no running loop, dropping event: %s", exc)

    async def _process_inbound(self, event: dict[str, Any]) -> None:
        """Read thread context and dispatch to InboundLoop master orchestrator."""
        if self._inbound_loop is None:
            logger.debug("InboundLoop not wired — dropping inbound event")
            return
        if self._session is None or self._session.page is None:
            return
        from sns_addict.actions.dm import DMActions
        from sns_addict.actions.humanize import Humanizer

        dma = DMActions(self._session.page, Humanizer())
        thread_href = str(event.get("thread_href") or "")
        if "/direct/t/" in thread_href:
            thread_id = thread_href.split("/direct/t/")[-1].rstrip("/")
        else:
            thread_id = thread_href
        if not thread_id:
            return
        try:
            async with self._browser_action_lock:
                messages = await dma.read_thread(thread_id, limit=5)
                metadata = await _read_thread_metadata(self._session.page)
        except Exception as exc:
            logger.warning("read_thread failed for %s: %s", _hash_thread(thread_id), exc)
            return
        if not messages:
            return
        last = messages[-1]
        if last.get("is_self"):
            return
        text = str(last.get("text") or "")
        msg_event: dict[str, Any] = {
            "thread_id": thread_id,
            "text": text,
            "ts": time.time(),
            "message_id": hashlib.sha256(
                f"{thread_id}{text}".encode("utf-8")
            ).hexdigest()[:16],
            **metadata,
        }
        await self._inbound_loop.on_inbound(msg_event)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SendResult:
        """Send a DM. Fire-and-best-effort: no retry on failure (duplicate-DM risk).

        ``chat_id`` is the Instagram thread id; ``content`` is the message text.
        ``reply_to`` and ``metadata`` are accepted for BasePlatformAdapter
        compatibility but unused — IG DMs have no native reply-threading.
        """
        del reply_to, metadata
        if self._session is None or self._session.page is None:
            return SendResult(
                success=False,
                error="adapter not connected",
                retryable=False,
            )
        from sns_addict.actions.dm import DMActions
        from sns_addict.actions.humanize import Humanizer

        dma = DMActions(self._session.page, Humanizer())
        thread_hash = _hash_thread(chat_id)
        start = time.time()
        try:
            async with self._browser_action_lock:
                await dma.send(chat_id, content)
        except Exception as exc:
            logger.warning("DM send failed for %s: %s", thread_hash, exc)
            await append_event(
                "send_failed",
                thread_id_hash=thread_hash,
                error=str(exc)[:200],
            )
            return SendResult(
                success=False,
                error=str(exc)[:200],
                retryable=False,
            )
        latency_ms = int((time.time() - start) * 1000)
        await append_event(
            "reply_sent",
            thread_id_hash=thread_hash,
            latency_ms=latency_ms,
        )
        if _f3_mode_enabled(self.config):
            try:
                await self._append_f3_reply(chat_id, content)
            except Exception as exc:
                logger.debug("f3 capture failed (ignored): %s", exc)
        return SendResult(
            success=True,
            message_id=hashlib.sha256(
                f"{chat_id}{content}{start}".encode("utf-8")
            ).hexdigest()[:16],
        )

    async def _append_f3_reply(self, thread_id: str, text: str) -> None:
        import aiofiles

        REPLIES_F3_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "thread_id_hash": _hash_thread(thread_id),
            "input": "",
            "output": text,
            "context": [],
        }
        async with aiofiles.open(REPLIES_F3_PATH, "a", encoding="utf-8") as f:
            await f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        """Return minimal chat info. sns-addict only handles 1:1 DMs in C1."""
        return {
            "name": _hash_thread(chat_id),
            "type": "dm",
            "platform": "sns_addict",
        }

    async def invoke_llm(self, event: dict[str, Any]) -> str:
        """Call the configured LLM backend. Returns reply string only — never sends.

        Hermes auxiliary clients remain the first choice. In standalone/npm
        installs, explicit OpenAI-compatible environment configuration can act
        as a fallback. SOUL.md is injected as the system prompt; the inbound
        thread text becomes the user message body. Raises ``RuntimeError`` when
        no backend is available, and ``ValueError`` when the LLM returns an
        empty/null response.
        """
        backend = resolve_llm_backend(
            "sns_addict_reply",
            hermes_getter=get_async_text_auxiliary_client,
            hermes_auxiliary_importable=_hermes_auxiliary_available,
        )
        client, model = backend.client, backend.model
        if client is None:
            hint = backend.status.setup_hint or "No LLM backend available"
            raise RuntimeError(hint)

        soul_path = Path.home() / ".hermes" / "SOUL.md"
        soul_content = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": soul_content},
                {"role": "user", "content": str(event.get("text") or "")},
            ],
            max_tokens=300,
            temperature=0.8,
        )
        reply = response.choices[0].message.content
        if not reply:
            raise ValueError("LLM returned empty/null response")
        return reply

    async def halt(self, reason: str) -> None:
        """Mark state as halted (HaltNow / identity-canary path)."""
        async def _apply(s: State) -> State:
            s.session_state = "halted"
            s.halt_reason = reason
            return s

        await self._state_store.update(_apply)
        logger.warning("SnsAddictAdapter halted: %s", reason)

    async def _watch_state(self) -> None:
        """Poll state.json every 5 s; act on dashboard state/runtime-mode signals.

        On startup, an immediate read precedes the polling loop so that an
        already-``active`` state.json is honored without a 5 s delay.
        """
        try:
            state = await self._state_store.read()
            if _should_connect(state) and not self.is_connected:
                logger.info(
                    "state_transition",
                    extra={
                        "from_state": "unknown",
                        "to_state": "active",
                        "action": "connect",
                    },
                )
                await self.connect()
        except Exception as exc:
            logger.debug("state watcher initial read error: %s", exc)

        last_mtime: Optional[float] = None
        while True:
            await asyncio.sleep(5)
            try:
                state_path = self._state_store._path  # noqa: SLF001
                if not state_path.exists():
                    continue
                mtime = state_path.stat().st_mtime
                if mtime == last_mtime:
                    continue
                last_mtime = mtime
                state = await self._state_store.read()
                if _should_connect(state) and not self.is_connected:
                    logger.info(
                        "state_transition",
                        extra={
                            "from_state": "inactive",
                            "to_state": "active",
                            "action": "connect",
                        },
                    )
                    await self.connect()
                elif (
                    _should_disconnect(state)
                    and self.is_connected
                ):
                    logger.info(
                        "state_transition",
                        extra={
                            "from_state": "active",
                            "to_state": state.session_state,
                            "action": "disconnect",
                        },
                    )
                    await self.disconnect()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("state watcher error: %s", exc)


def _record_send_counter(state: State, thread_id: str) -> None:
    if not thread_id:
        return
    c = state.send_counters
    now = time.time()
    day_window_seconds = 24 * 60 * 60
    hour_window_seconds = 60 * 60
    if now - c.day_window_start > day_window_seconds:
        c.day_window_start = now
        c.day_count = 0
        c.per_friend_day = {}
        c.per_friend_hour = {}
    c.day_count += 1
    c.per_friend_day[thread_id] = c.per_friend_day.get(thread_id, 0) + 1
    hour_list = [t for t in c.per_friend_hour.get(thread_id, []) if now - t < hour_window_seconds]
    hour_list.append(now)
    c.per_friend_hour[thread_id] = hour_list


def _thread_id_from_href(href: str) -> str:
    """Extract an Instagram direct thread id from absolute or relative href."""
    if "/direct/t/" not in href:
        return ""
    tail = href.split("/direct/t/", 1)[-1]
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    return tail.strip("/")


def _inbox_thread_key(row_index: int, thread: dict[str, Any]) -> str:
    """Return a stable key for one inbox row across preview text changes."""
    href = str(thread.get("href") or "")
    thread_id = _thread_id_from_href(href)
    if thread_id:
        return thread_id
    title = str(thread.get("title") or "").strip()
    if not title:
        row_text = str(thread.get("text") or "").strip()
        title = next((part.strip() for part in row_text.splitlines() if part.strip()), "")
    if title:
        return f"row:{row_index}:title:{_hash_text(title)}"
    row_text = str(thread.get("text") or "").strip()
    if not row_text:
        return f"row:{row_index}:empty"
    return f"row:{row_index}:preview:{_hash_text(row_text[:40])}"


async def _read_thread_metadata(page: Any) -> dict[str, Any]:
    """Best-effort explicit 1:1/username metadata for autopilot-lite gating."""
    try:
        raw = await page.evaluate(
            """
            () => {
                const main = document.querySelector('[role="main"]') || document.body;
                const header = main?.querySelector('header') || main;
                const labels = Array.from(header.querySelectorAll('h1,h2,h3,a,span'))
                    .map((el) => (el.textContent || '').trim())
                    .filter(Boolean)
                    .filter((txt) => txt.length >= 2 && txt.length <= 80);
                const seen = [];
                for (const label of labels) {
                    if (!seen.includes(label)) seen.push(label);
                }
                const title = seen[0] || '';
                const joined = seen.join(' ');
                const isGroup = /,| and | 외 |명|members|participants|group/i.test(title)
                    || /members|participants|group/i.test(joined);
                const usernames = [];
                for (const anchor of Array.from(header.querySelectorAll('a[href]'))) {
                    try {
                        const url = new URL(anchor.getAttribute('href'), window.location.origin);
                        if (url.origin !== window.location.origin) continue;
                        const parts = url.pathname.split('/').filter(Boolean);
                        if (parts.length !== 1) continue;
                        const username = parts[0];
                        if ([
                            'accounts', 'direct', 'explore', 'p', 'reel', 'stories',
                            'about', 'developer', 'privacy', 'terms'
                        ].includes(username)) continue;
                        if (/^[A-Za-z0-9._]{1,30}$/.test(username) && !usernames.includes(username)) {
                            usernames.push(username);
                        }
                    } catch (_) {}
                }
                return { title, is_group: !!isGroup, usernames };
            }
            """
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("thread metadata read failed: %s", exc)
        return {}

    title = str(raw.get("title") or "").strip() if isinstance(raw, dict) else ""
    is_group = bool(raw.get("is_group")) if isinstance(raw, dict) else False
    usernames_raw = raw.get("usernames") if isinstance(raw, dict) else None
    usernames = [
        str(username).strip()
        for username in (usernames_raw if isinstance(usernames_raw, list) else [])
        if str(username).strip()
    ]
    if is_group:
        return {"chat_type": "group", "is_group": True}
    if len(usernames) == 1:
        return {"chat_type": "dm", "username": usernames[0], "is_group": False}
    return {"chat_type": "unknown", "is_group": False, "title": title}


def _set_session_active(state: State) -> State:
    state.session_state = "active"
    if state.runtime_mode == "stopped":
        state.runtime_mode = "approval"
    state.halt_reason = None
    return state


def _set_session_stopped(state: State) -> State:
    state.session_state = "stopped"
    return state


def _should_connect(state: State) -> bool:
    if state.session_state in {"stopped", "halted", "challenge_pending"}:
        return False
    return state.runtime_mode in {"observe", "approval", "autopilot_lite"}


def _should_disconnect(state: State) -> bool:
    return state.session_state in {"stopped", "halted"} or state.runtime_mode == "stopped"


def create_adapter(cfg: PlatformConfig) -> SnsAddictAdapter:
    """Factory: instantiate adapter and spawn the state.json watcher.

    The watcher attaches to the running loop. If no loop is running yet
    (synchronous plugin discovery), spawn is deferred to first ``connect()``.
    """
    adapter = SnsAddictAdapter(cfg, _resolve_platform())
    try:
        loop = asyncio.get_running_loop()
        adapter._state_watcher_task = loop.create_task(adapter._watch_state())
    except RuntimeError:
        pass
    return adapter

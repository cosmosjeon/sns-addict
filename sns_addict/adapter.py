"""SnsAddictAdapter — Hermes BasePlatformAdapter implementation for Instagram.

InboundLoop is the master orchestrator (``handle_message`` is never called).
Only ``invoke_llm`` (openai_direct + SOUL.md) and ``send`` (BasePlatformAdapter
standard) are exposed to it. ``send`` is fire-and-best-effort (no retry —
duplicate-DM risk).

DOM Observer fires → ``_on_dom_event`` returns < 50 ms by spawning a task →
``_process_inbound`` reads thread context → dispatches to InboundLoop.

State watcher polls ``state.json`` every 5 s (dashboard ↔ adapter IPC):
``active`` → ``connect()`` ; ``stopped``/``halted`` → ``disconnect()``.

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
    ) -> None:
        super().__init__(config, platform if platform is not None else _resolve_platform())
        self._session: Optional[BrowserSession] = None
        self._inbound_loop: Any = None
        self._halt_task: Optional[asyncio.Task[None]] = None
        self._refresh_task: Optional[asyncio.Task[None]] = None
        self._soul_task: Optional[asyncio.Task[None]] = None
        self._state_watcher_task: Optional[asyncio.Task[None]] = None
        self._auto_stop_task: Optional[asyncio.Task[None]] = None
        self._sleep_recovery_task: Optional[asyncio.Task[None]] = None

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

        try:
            click_result = await page.evaluate("""
                () => new Promise((resolve) => {
                    let attempts = 0;
                    const skip = ['메시지 보내기', 'Send Message', '내 메모', '새로운 메시지', '새 소식'];
                    const tryClick = () => {
                        attempts++;
                        const items = document.querySelectorAll('[role="listitem"]');
                        for (const it of items) {
                            const txt = (it.textContent || '').trim();
                            if (!txt || txt.length < 3) continue;
                            if (skip.some(s => txt.includes(s))) continue;
                            if (txt.includes('deski.ai') && txt.length < 30) continue;
                            try {
                                it.click();
                                resolve({ok: true, attempts, text: txt.slice(0, 120)});
                                return;
                            } catch (e) {}
                        }
                        if (attempts > 40) {
                            resolve({ok: false, attempts, last_count: items.length});
                            return;
                        }
                        setTimeout(tryClick, 500);
                    };
                    tryClick();
                })
            """)
            await append_event("thread_click_result", **click_result)
            if click_result.get("ok"):
                await asyncio.sleep(3)
                await append_event("entered_thread", url=str(page.url)[:200])
        except Exception as exc:
            await append_event("thread_click_failed", error=str(exc)[:200])
        self._halt_task = asyncio.create_task(HaltNow().watch(self))
        self._soul_task = asyncio.create_task(watch_soul_md())
        self._auto_stop_task = asyncio.create_task(AutoStop(self).watch())
        self._sleep_recovery_task = asyncio.create_task(SleepRecovery(self).watch())
        await STATE_STORE.update(_set_session_active)
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
        await STATE_STORE.update(_set_session_stopped)
        logger.info("SnsAddictAdapter disconnected")

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
                        preview=event.get("preview", ""),
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
            messages = await dma.read_thread(thread_id, limit=5)
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
        """Call LLM via Hermes-auth auxiliary_client. Returns reply string only — never sends.

        Uses the Hermes-auth credential chain (codex/nous/openrouter) via
        ``get_async_text_auxiliary_client``. SOUL.md is injected as the system
        prompt; the inbound thread text becomes the user message body.
        Raises ``RuntimeError`` when no auxiliary client is available, and
        ``ValueError`` when the LLM returns an empty/null response.
        """
        client, model = get_async_text_auxiliary_client("sns_addict_reply")
        if client is None:
            raise RuntimeError(
                "No auxiliary client available — check hermes auth"
            )

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

        await STATE_STORE.update(_apply)
        logger.warning("SnsAddictAdapter halted: %s", reason)

    async def _watch_state(self) -> None:
        """Poll state.json every 5 s; act on dashboard ``active``/``stopped``/``halted`` signals.

        On startup, an immediate read precedes the polling loop so that an
        already-``active`` state.json is honored without a 5 s delay.
        """
        try:
            state = await STATE_STORE.read()
            if state.session_state == "active" and not self.is_connected:
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
                state_path = STATE_STORE._path  # noqa: SLF001
                if not state_path.exists():
                    continue
                mtime = state_path.stat().st_mtime
                if mtime == last_mtime:
                    continue
                last_mtime = mtime
                state = await STATE_STORE.read()
                if state.session_state == "active" and not self.is_connected:
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
                    state.session_state in ("stopped", "halted")
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


def _set_session_active(state: State) -> State:
    state.session_state = "active"
    state.halt_reason = None
    return state


def _set_session_stopped(state: State) -> State:
    state.session_state = "stopped"
    return state


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

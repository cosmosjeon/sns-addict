"""Local runtime supervisor for dashboard-started sns-addict sessions."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from sns_addict.onboarding import ensure_local_product_files
from sns_addict.persistence.allowlist import AllowlistStore
from sns_addict.persistence.events import append_event
from sns_addict.persistence.state import RuntimeMode, State, StateStore

logger = logging.getLogger(__name__)

RuntimeStatus = Literal["stopped", "starting", "running", "stopping", "error"]
_HALTS_PATH = Path.home() / ".hermes" / "HALT_NOW"


class RuntimeSupervisor:
    """Idempotent owner of the local browser observer/adapter runtime."""

    def __init__(
        self,
        *,
        state_store: StateStore | None = None,
        allowlist_store: AllowlistStore | None = None,
        halt_path: Path = _HALTS_PATH,
        adapter_factory: Callable[[StateStore], Any] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._state_store = state_store or StateStore()
        self._allowlist_store = allowlist_store or AllowlistStore()
        self._halt_path = halt_path
        self._adapter_factory = adapter_factory
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._adapter: Any | None = None
        self._status: RuntimeStatus = "stopped"
        self._last_error: str | None = None
        self._started_at: float | None = None
        self._updated_at: float | None = None

    async def start(self, mode: RuntimeMode = "approval") -> dict[str, Any]:
        """Ensure the local adapter runtime exists and is in a safe mode."""
        if mode == "stopped":
            mode = "approval"
        ensure_local_product_files(
            state_store=self._state_store,
            allowlist_store=self._allowlist_store,
        )
        self._clear_halt_now()

        async def _activate(state: State) -> State:
            state.session_state = "active"
            state.runtime_mode = mode
            state.halt_reason = None
            return state

        await self._state_store.update(_activate)

        if self._task is None or self._task.done():
            self._stop_event = asyncio.Event()
            self._status = "starting"
            self._last_error = None
            self._started_at = time.time()
            self._updated_at = self._started_at
            self._task = asyncio.create_task(self._run(), name="sns-addict-runtime")
        return self.health()

    async def stop(self, *, touch_halt: bool = True) -> dict[str, Any]:
        """Stop browser/runtime and optionally touch HALT_NOW for fail-closed safety."""
        self._status = "stopping" if self._task is not None else "stopped"
        self._updated_at = time.time()
        if touch_halt:
            self._halt_path.parent.mkdir(parents=True, exist_ok=True)
            self._halt_path.touch()

        async def _stopped(state: State) -> State:
            state.session_state = "stopped"
            state.runtime_mode = "stopped"
            return state

        await self._state_store.update(_stopped)
        if self._stop_event is not None:
            self._stop_event.set()
        if self._adapter is not None:
            try:
                await self._adapter.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.debug("adapter disconnect during stop failed: %s", exc)
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
        self._status = "stopped"
        self._updated_at = time.time()
        return self.health()

    def health(self) -> dict[str, Any]:
        task_active = self._task is not None and not self._task.done()
        browser_connected = bool(getattr(self._adapter, "is_connected", False))
        llm_backend = _llm_backend_status()
        warning = None if llm_backend["available"] else (
            llm_backend.get("setup_hint")
            or "LLM backend unavailable; observing can run, but drafts may fail."
        )
        return {
            "status": self._status,
            "runtime_task_active": task_active,
            "browser_connected": browser_connected,
            "started_at": self._started_at,
            "updated_at": self._updated_at,
            "last_error": self._last_error,
            "llm_available": llm_backend["available"],
            "llm_backend": llm_backend,
            "warning": warning,
        }

    def reset_for_tests(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._stop_event = None
        self._adapter = None
        self._status = "stopped"
        self._last_error = None
        self._started_at = None
        self._updated_at = None

    async def _run(self) -> None:
        try:
            self._adapter = self._build_adapter()
            await self._adapter.connect()
            self._status = "running"
            self._updated_at = time.time()
            await append_event("runtime_started", mode="local_dashboard")

            while self._stop_event is not None and not self._stop_event.is_set():
                state = await self._state_store.read()
                if state.session_state in {"stopped", "halted"} or state.runtime_mode == "stopped":
                    break
                await self._sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("runtime supervisor failed: %s", exc)
            self._status = "error"
            self._last_error = str(exc)[:200]
            self._updated_at = time.time()
            try:
                await append_event("runtime_error", error=self._last_error)
            except Exception:
                pass
        finally:
            try:
                if self._adapter is not None:
                    await self._adapter.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.debug("adapter disconnect in runtime finalizer failed: %s", exc)
            if self._status != "error":
                self._status = "stopped"
            self._updated_at = time.time()

    def _build_adapter(self) -> Any:
        if self._adapter_factory is not None:
            return self._adapter_factory(self._state_store)

        from sns_addict.adapter import PlatformConfig, SnsAddictAdapter  # noqa: PLC0415
        from sns_addict.actions.humanize import Humanizer  # noqa: PLC0415
        from sns_addict.guardrails.dedup import Dedup  # noqa: PLC0415
        from sns_addict.guardrails.identity_canary import IdentityCanary  # noqa: PLC0415
        from sns_addict.guardrails.loop_detector import LoopDetector  # noqa: PLC0415
        from sns_addict.guardrails.quiet_hours import QuietHours  # noqa: PLC0415
        from sns_addict.guardrails.volume_cap import VolumeCap  # noqa: PLC0415
        from sns_addict.loops.inbound import GuardrailsBundle, InboundLoop  # noqa: PLC0415

        cfg = PlatformConfig(enabled=True, extra={"runtime": "dashboard"})
        adapter = SnsAddictAdapter(cfg, state_store=self._state_store)
        guardrails = GuardrailsBundle(
            canary=IdentityCanary(),
            quiet_hours=QuietHours(),
            loop_detector=LoopDetector(),
            dedup=Dedup(),
            volume=VolumeCap(self._state_store),
        )
        inbound = InboundLoop(
            adapter=adapter,
            guardrails=guardrails,
            humanizer=Humanizer(),
            state_store=self._state_store,
            allowlist_store=self._allowlist_store,
        )
        adapter.set_inbound_loop(inbound)
        return adapter

    def _clear_halt_now(self) -> None:
        try:
            self._halt_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("failed to clear HALT_NOW: %s", exc)


def _llm_backend_status() -> dict[str, Any]:
    try:
        from sns_addict import adapter as adapter_mod  # noqa: PLC0415
        from sns_addict.llm_backend import llm_backend_status  # noqa: PLC0415

        return llm_backend_status(
            hermes_getter=getattr(adapter_mod, "get_async_text_auxiliary_client"),
            hermes_auxiliary_importable=bool(
                getattr(adapter_mod, "_hermes_auxiliary_available", False)
            ),
        ).to_dict()
    except Exception:
        return {
            "backend_name": "Unknown",
            "available": False,
            "model": None,
            "setup_hint": "LLM backend status check failed; drafts may fail.",
            "hermes_auxiliary_importable": False,
        }

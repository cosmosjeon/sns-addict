"""Non-developer onboarding helpers for local sns-addict product startup.

This module intentionally avoids Hermes gateway lifecycle and Instagram
credential handling. It only prepares local files and opens a headful Chromium
login flow where the owner types credentials directly into Instagram.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Literal

from sns_addict.persistence.allowlist import Allowlist, AllowlistStore
from sns_addict.persistence.state import State, StateStore

logger = logging.getLogger(__name__)

_HERMES_DIR = Path.home() / ".hermes"
_SNS_DIR = _HERMES_DIR / "sns-addict"
_PROFILE_DIR = _SNS_DIR / "profile"
_LOGS_DIR = _SNS_DIR / "logs"
_ALERTS_DIR = _SNS_DIR / "alerts"
_CONVERSATIONS_DIR = _LOGS_DIR / "conversations"
_SOUL_MD = _HERMES_DIR / "SOUL.md"
_PACKAGED_SOUL = Path(__file__).parent.parent / "assets" / "SOUL.md"
_COOKIE_FILE = _PROFILE_DIR / "Default" / "Cookies"
_COOKIE_MIN_BYTES = 1024

LoginState = Literal[
    "disconnected",
    "login_needed",
    "connecting",
    "connected",
    "profile_in_use",
    "error",
]


def ensure_local_product_files(
    *,
    state_store: StateStore | None = None,
    allowlist_store: AllowlistStore | None = None,
) -> dict[str, str]:
    """Create the local product shell files without forcing Instagram login.

    Safe defaults are preserved: runtime stays stopped unless an existing state
    file says otherwise, allowlist starts empty, and F3 remains disabled.
    """
    for directory in (_SNS_DIR, _PROFILE_DIR, _LOGS_DIR, _ALERTS_DIR, _CONVERSATIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    if not _SOUL_MD.exists() and _PACKAGED_SOUL.exists():
        _SOUL_MD.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_PACKAGED_SOUL, _SOUL_MD)

    state_store = state_store or StateStore()
    allowlist_store = allowlist_store or AllowlistStore()
    state_path = state_store._path  # noqa: SLF001
    allowlist_path = allowlist_store._path  # noqa: SLF001

    if not state_path.exists():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            State(session_state="stopped", runtime_mode="stopped").model_dump_json(indent=2),
            encoding="utf-8",
        )

    if not allowlist_path.exists():
        allowlist_path.parent.mkdir(parents=True, exist_ok=True)
        allowlist_path.write_text(Allowlist().model_dump_json(indent=2), encoding="utf-8")

    return {
        "sns_dir": str(_SNS_DIR),
        "profile_dir": str(_PROFILE_DIR),
        "state_path": str(state_path),
        "allowlist_path": str(allowlist_path),
        "soul_path": str(_SOUL_MD),
    }


class InstagramLoginSupervisor:
    """Owns one asynchronous, owner-driven Instagram login attempt."""

    def __init__(
        self,
        *,
        profile_dir: Path = _PROFILE_DIR,
        cookie_file: Path = _COOKIE_FILE,
        session_factory: Callable[[Path], Any] | None = None,
        login_func: Callable[[Any], Any] | None = None,
    ) -> None:
        self._profile_dir = profile_dir
        self._cookie_file = cookie_file
        self._session_factory = session_factory
        self._login_func = login_func
        self._task: asyncio.Task[None] | None = None
        self._session: Any | None = None
        self._state: LoginState = "disconnected"
        self._last_error: str | None = None
        self._started_at: float | None = None
        self._updated_at: float | None = None

    def status(self) -> dict[str, Any]:
        state = self._derived_state()
        return {
            "state": state,
            "profile_dir_exists": self._profile_dir.exists(),
            "cookies_present": self._cookies_present(),
            "browser_active": self._session is not None and state == "connecting",
            "started_at": self._started_at,
            "updated_at": self._updated_at,
            "error": self._last_error if state in {"error", "profile_in_use"} else None,
        }

    async def connect(self) -> dict[str, Any]:
        """Start a headful Chromium login flow if one is not already running."""
        ensure_local_product_files()
        if self._profile_lock_present():
            self._state = "profile_in_use"
            self._last_error = _profile_in_use_message(self._profile_dir)
            self._updated_at = time.time()
            return self.status()
        if self._task is not None and not self._task.done():
            return self.status()
        self._state = "connecting"
        self._last_error = None
        now = time.time()
        self._started_at = now
        self._updated_at = now
        self._task = asyncio.create_task(self._run_login(), name="sns-addict-ig-login")
        return self.status()

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    def reset_for_tests(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._session = None
        self._state = "disconnected"
        self._last_error = None
        self._started_at = None
        self._updated_at = None

    async def _run_login(self) -> None:
        try:
            session_factory = self._session_factory
            login_func = self._login_func
            if session_factory is None or login_func is None:
                from sns_addict.browser.login import interactive_login  # noqa: PLC0415
                from sns_addict.browser.session import BrowserSession  # noqa: PLC0415

                session_factory = BrowserSession
                login_func = interactive_login

            self._session = session_factory(self._profile_dir)
            await self._session.start()
            success = bool(await login_func(self._session))
            self._state = "connected" if success else "login_needed"
        except asyncio.CancelledError:
            self._state = "disconnected"
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Instagram login flow failed: %s", exc)
            if _is_profile_in_use_error(exc):
                self._state = "profile_in_use"
                self._last_error = _profile_in_use_message(self._profile_dir)
            else:
                self._state = "error"
                self._last_error = str(exc)[:200]
        finally:
            try:
                if self._session is not None:
                    await self._session.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("login BrowserSession stop failed: %s", exc)
            self._session = None
            self._updated_at = time.time()

    def _derived_state(self) -> LoginState:
        if self._task is not None and not self._task.done():
            return "connecting"
        if self._state in {"error", "profile_in_use"}:
            return self._state
        if self._state == "connected" or self._cookies_present():
            return "connected"
        if self._profile_dir.exists():
            return "login_needed"
        return "disconnected"

    def _cookies_present(self) -> bool:
        return _instagram_session_cookie_present(self._cookie_file)

    def _profile_lock_present(self) -> bool:
        return any(
            os.path.lexists(str(self._profile_dir / name))
            for name in ("SingletonLock", "SingletonCookie", "SingletonSocket")
        )


def _instagram_session_cookie_present(cookie_file: Path) -> bool:
    """Return True only when Chrome cookies contain authenticated IG markers."""
    try:
        if not cookie_file.exists() or cookie_file.stat().st_size <= _COOKIE_MIN_BYTES:
            return False
    except OSError:
        return False
    try:
        con = sqlite3.connect(f"file:{cookie_file}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select name from cookies where host_key like ? and name in (?, ?, ?)",
                ("%instagram.com", "sessionid", "ds_user_id", "rur"),
            ).fetchall()
        finally:
            con.close()
        names = {str(row[0]) for row in rows}
        return "sessionid" in names and "ds_user_id" in names
    except sqlite3.Error:
        return False


def _is_profile_in_use_error(exc: Exception) -> bool:
    message = str(exc)
    return "ProcessSingleton" in message or "profile is already in use" in message


def _profile_in_use_message(profile_dir: Path) -> str:
    return (
        "Another Chromium window is already using this Instagram browser profile. "
        "Click Emergency Stop, close the sns-addict Instagram Chromium window, then try "
        f"Connect Instagram again. Profile: {profile_dir}"
    )

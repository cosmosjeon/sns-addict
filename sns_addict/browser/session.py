"""Patchright BrowserSession — headful, bundled Chromium, Korean-locale persistent profile."""
from __future__ import annotations

import logging
import subprocess
import sys
import asyncio
from pathlib import Path
from typing import Optional

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)

PROFILE_DIR = Path.home() / ".hermes" / "sns-addict" / "profile"
IG_HOME = "https://www.instagram.com/"

LOGGED_IN_SELECTORS = [
    'svg[aria-label="홈"]',
    'svg[aria-label="Home"]',
    'a[href="/direct/inbox/"]',
    'a[href*="/direct/inbox"]',
]


class BrowserSession:
    def __init__(self, profile_dir: Path = PROFILE_DIR):
        self._profile_dir = profile_dir
        self._pw: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> Page:
        """Launch persistent context. NOT idempotent — call stop() before re-starting."""
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        try:
            self._context = await self._launch_context()
        except Exception as exc:
            if not _is_missing_browser_error(exc):
                raise
            logger.warning("Bundled Chromium missing; running patchright install chromium once")
            await asyncio.to_thread(_install_chromium)
            self._context = await self._launch_context()
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        logger.info("BrowserSession started, profile=%s", self._profile_dir)
        return self._page

    async def _launch_context(self) -> BrowserContext:
        if self._pw is None:
            raise RuntimeError("Playwright not started")
        return await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=False,
            no_viewport=True,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 800},
            # bundled Chromium only — passing a system-chrome channel arg breaks isolation (Metis decision)
        )

    async def stop(self) -> None:
        """Idempotent stop."""
        try:
            if self._context:
                await self._context.close()
        except Exception as exc:
            logger.debug("context close error (ignored): %s", exc)
        try:
            if self._pw:
                await self._pw.stop()
        except Exception as exc:
            logger.debug("playwright stop error (ignored): %s", exc)
        self._context = None
        self._pw = None
        self._page = None

    async def is_logged_in(self) -> bool:
        """Check if current page shows IG home feed (logged-in state)."""
        if not self._page:
            return False
        for sel in LOGGED_IN_SELECTORS:
            try:
                loc = self._page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    return True
            except Exception:
                continue
        return False

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context


def _is_missing_browser_error(exc: Exception) -> bool:
    message = str(exc)
    return "Executable doesn't exist" in message or "playwright install" in message.lower()


def _install_chromium() -> None:
    subprocess.run(
        [sys.executable, "-m", "patchright", "install", "chromium"],
        check=True,
    )

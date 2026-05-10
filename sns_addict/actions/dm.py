"""DM send/read actions via Patchright page interaction.

Click-only navigation (NO direct goto on /direct/t/{thread_id}/) per anti-detection policy.
Send is fire-and-best-effort: no retry on failure to avoid duplicate-DM risk.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from patchright.async_api import Page

from sns_addict.actions.humanize import Humanizer
from sns_addict.browser.selectors import click_first_matching, query_all_matching

logger = logging.getLogger(__name__)


class DMActions:
    _page: Page
    _humanizer: Humanizer

    def __init__(self, page: Page, humanizer: Humanizer) -> None:
        self._page = page
        self._humanizer = humanizer

    async def _navigate_to_thread(self, thread_id: str) -> None:
        """Navigate to a DM thread via inbox click. Never goto /direct/t/ URL directly."""
        _ = await self._page.goto(
            "https://www.instagram.com/direct/inbox/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(2)
        threads = await query_all_matching(self._page, "dm_thread_item")
        for thread in threads:
            try:
                href = await cast(Any, thread).get_attribute("href") or ""
                if thread_id in href:
                    await thread.click()
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue
        _ = await click_first_matching(self._page, "dm_thread_item")
        await asyncio.sleep(2)

    async def send(self, thread_id: str, text: str) -> dict[str, Any]:
        """Send a DM. Fire-and-best-effort: no retry on failure (duplicate-DM risk)."""
        await self._navigate_to_thread(thread_id)
        _ = await click_first_matching(self._page, "dm_message_input", timeout=10000)
        await asyncio.sleep(0.3)
        for char in text:
            await self._page.keyboard.type(char, delay=self._humanizer.next_typing_delay())
        await asyncio.sleep(self._humanizer.next_pause("send"))
        _ = await click_first_matching(self._page, "dm_send_button")
        logger.info("DM sent to thread %s (%d chars)", thread_id[:8], len(text))
        return {"sent": True, "thread_id": thread_id, "text": text}

    async def read_thread(self, thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Read the last N messages from a thread."""
        await self._navigate_to_thread(thread_id)
        await asyncio.sleep(2)
        msgs = await self._page.evaluate(
            f"""
            (() => {{
                const items = document.querySelectorAll('[role="listitem"]');
                return Array.from(items).slice(-{limit}).map(it => ({{
                    text: (it.textContent || '').trim().slice(0, 500),
                    is_self: !!(it.querySelector('[aria-label*="보낸"]') ||
                                it.querySelector('[aria-label*="Sent"]')),
                }}));
            }})()
            """
        )
        return cast(list[dict[str, Any]], msgs) if msgs else []

    async def list_inbox_threads(self) -> list[dict[str, Any]]:
        """List inbox threads with href, title, and unread flag."""
        _ = await self._page.goto(
            "https://www.instagram.com/direct/inbox/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        _ = await self._page.wait_for_selector('a[href^="/direct/t/"]', timeout=10000)
        threads = await self._page.evaluate(
            """
            (() => {
                const links = document.querySelectorAll('a[href^="/direct/t/"]');
                return Array.from(links).map(a => {
                    const text = (a.textContent || '').trim();
                    return {
                        href: a.href,
                        title: (a.querySelector('h3, span')?.textContent || '').trim(),
                        text,
                        unread: /unread|new message|읽지 않|새 메시지|안 읽은/i.test(text) ||
                                !!(a.querySelector('[aria-label*="읽지 않음"]') ||
                                   a.querySelector('[aria-label*="Unread"]')),
                    };
                });
            })()
            """
        )
        return cast(list[dict[str, Any]], threads) if threads else []

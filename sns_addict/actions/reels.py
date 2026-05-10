"""Reels actions — share a reel to a DM thread via Patchright UI flow.

Click-only navigation per the same anti-detection policy as ``dm.py``: open
the reel URL, trigger the share UI, target a DM thread, confirm. All pauses
flow through ``Humanizer`` so timings stay randomized. Any DOM failure is
caught and surfaced as ``return False`` with a log entry — callers must not
see Patchright exceptions bubble out of this module.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sns_addict.actions.humanize import Humanizer

logger = logging.getLogger(__name__)


class ReelsActions:
    _page: Any
    _humanizer: Humanizer

    def __init__(self, page: Any, humanizer: Humanizer) -> None:
        self._page = page
        self._humanizer = humanizer

    async def share_reel(self, reel_url: str, target_thread_id: str) -> bool:
        """Share ``reel_url`` to the DM thread ``target_thread_id``.

        Returns ``True`` on best-effort success, ``False`` if any DOM step
        raised. No exceptions propagate out of this method.
        """
        try:
            await self._page.goto(
                reel_url, wait_until="domcontentloaded", timeout=30000
            )
            await asyncio.sleep(self._humanizer.next_pause("thinking"))

            share_button = self._page.locator(
                'svg[aria-label="공유"], svg[aria-label="Share"], '
                'div[role="button"][aria-label*="Share"]'
            ).first
            await share_button.wait_for(state="visible", timeout=10000)
            await asyncio.sleep(self._humanizer.next_pause("send"))
            await share_button.click()

            target = self._page.locator(
                f'div[role="dialog"] a[href*="/direct/t/{target_thread_id}"], '
                f'div[role="dialog"] div[role="button"][data-thread-id="{target_thread_id}"]'
            ).first
            await target.wait_for(state="visible", timeout=10000)
            await asyncio.sleep(self._humanizer.next_pause("send"))
            await target.click()

            confirm = self._page.locator(
                'div[role="dialog"] div[role="button"]:has-text("보내기"), '
                'div[role="dialog"] div[role="button"]:has-text("Send")'
            ).first
            await confirm.wait_for(state="visible", timeout=10000)
            await asyncio.sleep(self._humanizer.next_pause("send"))
            await confirm.click()

            logger.info(
                "reel shared to thread %s", target_thread_id[:8]
            )
            return True
        except Exception as exc:
            logger.warning(
                "share_reel failed for thread %s: %s", target_thread_id[:8], exc
            )
            return False

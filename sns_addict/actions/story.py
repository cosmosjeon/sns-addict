"""Story actions — react to a story via Patchright UI flow.

Open the story URL, locate the reaction control, type the reaction, and send.
``Humanizer`` drives every pause so timings stay randomized. Any DOM failure
is caught and surfaced as ``return False`` with a log entry — Patchright
exceptions never propagate out of this module.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sns_addict.actions.humanize import Humanizer

logger = logging.getLogger(__name__)


class StoryActions:
    _page: Any
    _humanizer: Humanizer

    def __init__(self, page: Any, humanizer: Humanizer) -> None:
        self._page = page
        self._humanizer = humanizer

    async def react_to_story(self, story_url: str, reaction: str = "❤️") -> bool:
        """React to ``story_url`` with ``reaction`` (default heart emoji).

        Returns ``True`` on best-effort success, ``False`` if any DOM step
        raised. No exceptions propagate out of this method.
        """
        try:
            await self._page.goto(
                story_url, wait_until="domcontentloaded", timeout=30000
            )
            await asyncio.sleep(self._humanizer.next_pause("thinking"))

            reaction_input = self._page.locator(
                'textarea[placeholder*="답장"], textarea[placeholder*="Reply"], '
                'textarea[aria-label*="답장"], textarea[aria-label*="Reply"]'
            ).first
            await reaction_input.wait_for(state="visible", timeout=10000)
            await asyncio.sleep(self._humanizer.next_pause("send"))
            await reaction_input.click()

            for char in reaction:
                await self._page.keyboard.type(
                    char, delay=self._humanizer.next_typing_delay()
                )

            await asyncio.sleep(self._humanizer.next_pause("send"))
            await self._page.keyboard.press("Enter")

            logger.info("story reacted at %s", story_url)
            return True
        except Exception as exc:
            logger.warning("react_to_story failed for %s: %s", story_url, exc)
            return False

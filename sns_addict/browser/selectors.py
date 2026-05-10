"""Multi-fallback CSS selectors for Instagram DOM elements."""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class LocatorLike(Protocol):
    @property
    def first(self) -> "LocatorLike": ...

    async def wait_for(self, *, state: str, timeout: int) -> None: ...

    async def click(self) -> None: ...

    async def count(self) -> int: ...

    def nth(self, index: int) -> "LocatorLike": ...


class PageLike(Protocol):
    def locator(self, selector: str) -> LocatorLike: ...

SELECTORS: dict[str, list[str]] = {
    "dm_inbox_link": [
        'a[href="/direct/inbox/"]',
        'svg[aria-label="Direct"]',
        'svg[aria-label="메시지"]',
        'a[href*="direct"]',
    ],
    "dm_thread_list": [
        'div[role="listbox"]',
        'div[aria-label*="대화"]',
        'div[aria-label*="Chats"]',
    ],
    "dm_thread_item": [
        'div[role="listbox"] div[role="button"]',
        'a[href*="/direct/t/"]',
    ],
    "dm_message_input": [
        'div[role="textbox"]',
        'textarea[placeholder*="메시지"]',
        'textarea[placeholder*="Message"]',
        'p[data-lexical-editor="true"]',
    ],
    "dm_send_button": [
        'div[role="button"][aria-label*="보내기"]',
        'div[role="button"][aria-label*="Send"]',
        'button[type="submit"]',
    ],
    "cookie_banner_dismiss": [
        'button:has-text("모두 허용")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Accept")',
    ],
    "unread_badge": [
        '[aria-label*="읽지 않음"]',
        '[aria-label*="Unread"]',
        'span[class*="unread"]',
    ],
    "story_ring": [
        'div[role="button"] canvas',
        'div[aria-label*="스토리"]',
    ],
    "explore_link": [
        'a[href="/explore/"]',
        'svg[aria-label="탐색"]',
        'svg[aria-label="Explore"]',
    ],
}


async def click_first_matching(page: PageLike, key: str, timeout: int = 5000) -> bool:
    """Try each selector in order; click first visible one. Raises RuntimeError if all fail."""
    selectors = SELECTORS.get(key, [])
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.click()
            logger.debug("click_first_matching: hit %s via %s", key, sel)
            return True
        except Exception:
            logger.debug("click_first_matching: miss %s via %s", key, sel)
            continue
    raise RuntimeError(f"No selector matched for key={key!r}. Tried: {selectors}")


async def find_first_matching(page: PageLike, key: str, timeout: int = 5000) -> LocatorLike | None:
    """Return first visible ElementHandle for key, or None."""
    selectors = SELECTORS.get(key, [])
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            continue
    return None


async def query_all_matching(page: PageLike, key: str) -> list[LocatorLike]:
    """Return all elements matching first hit selector for key."""
    selectors = SELECTORS.get(key, [])
    for sel in selectors:
        try:
            locs = page.locator(sel)
            count = await locs.count()
            if count > 0:
                return [locs.nth(i) for i in range(count)]
        except Exception:
            continue
    return []

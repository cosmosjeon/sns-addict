"""Group DM actions — read/send in group DM threads.

Volume cap: 15/day/group (tracked per group_id separately in state.json).
Uses the same Patchright page object as DM actions.
"""
from __future__ import annotations

import logging
import time
from typing import Any, cast

from sns_addict.persistence.state import State, StateStore

logger = logging.getLogger(__name__)

GROUP_DAY_LIMIT = 15
GROUP_DAY_WINDOW_SECONDS = 86400


class GroupDMActions:
    """Read and send messages in Instagram group DM threads.

    Per-group daily cap (``GROUP_DAY_LIMIT``) is enforced by reading and
    updating ``State.group_send_counters`` — kept distinct from direct-DM
    counters in ``send_counters`` so direct and group volume cannot
    cross-contaminate.
    """

    def __init__(self, state_store: StateStore | None = None) -> None:
        if state_store is None:
            from sns_addict.adapter import STATE_STORE
            state_store = STATE_STORE
        self._state_store: StateStore = state_store

    async def read_group_thread(
        self, page: Any, group_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` recent messages from the given group thread."""
        await page.goto(
            f"https://www.instagram.com/direct/t/{group_id}/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        msgs = await page.evaluate(
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

    async def send_group_dm(self, page: Any, group_id: str, content: str) -> bool:
        """Send to a group thread iff per-group cap not yet reached."""
        if await self._cap_exceeded(group_id):
            logger.info("group_dm blocked (cap_exceeded) group=%s", group_id[:8])
            return False

        await page.goto(
            f"https://www.instagram.com/direct/t/{group_id}/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.fill('textarea[placeholder*="message"]', content)
        await page.keyboard.press("Enter")

        await self._record_send(group_id)
        logger.info(
            "group_dm sent group=%s len=%d", group_id[:8], len(content)
        )
        return True

    async def _cap_exceeded(self, group_id: str) -> bool:
        state = await self._state_store.read()
        now = time.time()
        if now - state.group_send_window_start > GROUP_DAY_WINDOW_SECONDS:
            return False
        return state.group_send_counters.get(group_id, 0) >= GROUP_DAY_LIMIT

    async def _record_send(self, group_id: str) -> None:
        async def _update(state: State) -> State:
            now = time.time()
            if now - state.group_send_window_start > GROUP_DAY_WINDOW_SECONDS:
                state.group_send_window_start = now
                state.group_send_counters = {}
            state.group_send_counters[group_id] = (
                state.group_send_counters.get(group_id, 0) + 1
            )
            return state

        _ = await self._state_store.update(_update)

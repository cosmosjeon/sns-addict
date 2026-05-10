"""Loop C — mood-driven active outreach.

Initiates DMs to allowlist friends based on current mood.
Volume cap: 2 active sends/day total (SHARED with inbound volume cap).
Only sends when mood is NOT "밤" (night) — nighttime is quiet.
All sends go through VolumeCapGuardrail.
"""
from __future__ import annotations

import logging
from typing import Any

from sns_addict.guardrails.volume_cap import VolumeCap
from sns_addict.persistence.allowlist import AllowlistStore
from sns_addict.persistence.state import StateStore

logger = logging.getLogger(__name__)

QUIET_MOOD = "밤"


class ActiveBehavior:
    """Mood-driven active outreach.

    Gates active sends behind three checks (in order):
        1. Mood gate    — current_mood == "밤" → quiet, no send.
        2. Allowlist    — thread_id must be in allowlist.
        3. Volume cap   — VolumeCap.exceeded(thread_id) blocks send.

    All three must pass for the adapter.send() call to fire.
    """

    def __init__(
        self,
        state_store: StateStore | None = None,
        allowlist_store: AllowlistStore | None = None,
        volume_cap: VolumeCap | None = None,
    ) -> None:
        if state_store is None:
            from sns_addict.adapter import STATE_STORE
            state_store = STATE_STORE
        self._state_store: StateStore = state_store
        self._allowlist_store: AllowlistStore = (
            allowlist_store if allowlist_store is not None else AllowlistStore()
        )
        self._volume_cap: VolumeCap = (
            volume_cap if volume_cap is not None else VolumeCap(state_store)
        )

    async def send_active_dm(self, adapter: Any, thread_id: str, content: str) -> bool:
        """Send an active (self-initiated) DM if all gates pass.

        Returns True iff the message was actually dispatched to the adapter.
        """
        thread_short = thread_id[:8] if thread_id else "?"
        logger.info("active_dm attempt thread=%s", thread_short)

        state = await self._state_store.read()
        if state.current_mood == QUIET_MOOD:
            logger.info("active_dm blocked (mood=밤) thread=%s", thread_short)
            return False

        allowlist = await self._allowlist_store.read()
        usernames = {f.username for f in allowlist.friends}
        if thread_id not in usernames:
            logger.info("active_dm blocked (not_in_allowlist) thread=%s", thread_short)
            return False

        if await self._volume_cap.exceeded(thread_id):
            logger.info("active_dm blocked (volume_cap) thread=%s", thread_short)
            return False

        await adapter.send(thread_id, content)
        await self._volume_cap.record(thread_id)
        logger.info("active_dm sent thread=%s len=%d", thread_short, len(content))
        return True

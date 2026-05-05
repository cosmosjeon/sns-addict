"""Quiet hours guardrail — port from legacy adapter:355-365."""
from __future__ import annotations

import datetime

QUIET_START_HOUR = 2   # 02:00
QUIET_END_HOUR = 8     # 08:00


class QuietHours:
    def is_active(self) -> bool:
        """Return True if current local time is in quiet window (02:00-08:00)."""
        hour = datetime.datetime.now().hour
        return QUIET_START_HOUR <= hour < QUIET_END_HOUR

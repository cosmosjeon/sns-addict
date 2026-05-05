"""Human-like timing randomization for anti-detection."""
from __future__ import annotations

import random


class Humanizer:
    """Provides randomized delays to mimic human typing and interaction patterns."""

    def next_typing_delay(self) -> float:
        """Return delay in ms between keystrokes (50-200ms)."""
        return random.uniform(50, 200)

    def next_pause(self, kind: str = "thinking") -> float:
        """Return pause duration in seconds for given interaction kind."""
        if kind == "thinking":
            return random.uniform(2, 30)
        elif kind == "send":
            return random.uniform(0.3, 1.5)
        elif kind == "scroll":
            return random.uniform(0.5, 3.0)
        else:
            return random.uniform(0.5, 2.0)

    def should_take_break(self) -> bool:
        """Return True ~5% of the time to simulate natural breaks."""
        return random.random() < 0.05

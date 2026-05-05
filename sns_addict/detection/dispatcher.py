"""Event dispatcher — routes DOM events to adapter callback.

C1 scope: DOM Observer is the only live source. WebSocket is a CYCLE 2
stub (``is_healthy`` is permanently False), so DOM events are never
suppressed by the WS-takes-priority rule from tech-arch.md:574-577.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

InboundCallback = Callable[[dict[str, Any]], Any]


class EventDispatcher:
    def __init__(self) -> None:
        self._callback: InboundCallback | None = None
        self.is_healthy: bool = False

    def set_callback(self, callback: InboundCallback) -> None:
        self._callback = callback

    async def on_dom_event(self, event: dict[str, Any]) -> None:
        if self._callback is None:
            return
        result = self._callback(event)
        if inspect.isawaitable(result):
            await result
        logger.debug("Dispatched DOM event: %s", event.get("kind"))

"""DOM Observer for Instagram unread badge detection via MutationObserver.

CRITICAL: MutationObserver throttles when tab is backgrounded.
Browser tab MUST stay foregrounded for reliable detection.
F3 pre-flight checklist requires this.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

DomEventCallback = Callable[[dict[str, Any]], Any]


_OBSERVER_SCRIPT = """
(function () {
    if (window.__snsAddictObserverInstalled) return;
    window.__snsAddictObserverInstalled = true;

    window.__sns_observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
            for (const node of m.addedNodes) {
                if (node.nodeType !== 1) continue;
                // unread badge 또는 새 thread item 감지
                const unread = node.querySelector?.('[aria-label*="읽지 않음"], [aria-label*="Unread"]');
                if (unread) {
                    const thread = node.closest('[role="listitem"], a[href^="/direct/t/"]');
                    if (thread) {
                        window.__sns_dom_event({
                            kind: 'inbound_likely',
                            thread_href: thread.href || null,
                            preview: thread.textContent?.slice(0, 100) || '',
                            ts: Date.now(),
                        });
                    }
                }
            }
        }
    });

    const observe = () => {
        const target = document.querySelector('[role="main"], [role="navigation"]');
        if (target) {
            window.__sns_observer.observe(target, { childList: true, subtree: true });
        } else {
            setTimeout(observe, 500);
        }
    };
    observe();
})();
"""


async def inject_dom_observer(page: Any, on_dom_event: DomEventCallback) -> None:
    """Inject MutationObserver into ``page`` and wire ``on_dom_event`` callback.

    The callback is invoked with a dict::

        {"kind": "inbound_likely", "thread_href": str | None,
         "preview": str, "ts": int}

    Notes:
        MutationObserver throttles when the browser tab is backgrounded.
        The owner is responsible for keeping the tab foregrounded; the F3
        pre-flight checklist enforces this.
    """
    await page.expose_function("__sns_dom_event", on_dom_event)
    await page.add_init_script(_OBSERVER_SCRIPT)
    logger.info("DOM Observer injected")

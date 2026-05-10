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

    // Polling-based detector: compares thread list text every 3s.
    // More robust than MutationObserver against Instagram's React re-renders
    // and aria-label drift. Detects new threads OR text changes that indicate
    // new inbound messages (e.g. "3 new messages", "개의 새 메시지").
    const knownThreads = new Map();
    let initialized = false;

    const UNREAD_PATTERNS = [
        'new message',
        '개의 새 메시지',
        '개의 안 읽은',
        '읽지 않음',
        'Unread',
    ];

    const hasUnreadHint = (text) => {
        for (const p of UNREAD_PATTERNS) {
            if (text.includes(p)) return true;
        }
        return false;
    };

    const stableKeyFor = (el) => {
        // Prefer /direct/t/ href when present (most stable).
        const link = el.tagName === 'A' ? el : (el.querySelector('a[href*="/direct/t/"]') || null);
        const href = link?.getAttribute('href');
        if (href) return { key: href, href };
        // Else use the first non-empty line (typically the username) — stable across re-renders.
        const text = (el.textContent || '').trim();
        const firstLine = text.split('\\n').map(s => s.trim()).filter(Boolean)[0] || '';
        return { key: 'name:' + firstLine.slice(0, 60), href: null };
    };

    let pollCount = 0;
    let lastMainText = '';
    const scanThreadView = () => {
        const main = document.querySelector('[role="main"]');
        if (!main) return;
        const text = (main.textContent || '').slice(-500);
        if (lastMainText && text !== lastMainText) {
            try {
                window.__sns_dom_event({
                    kind: 'inbound_likely',
                    thread_href: location.href,
                    preview: text.slice(-200),
                    ts: Date.now(),
                });
            } catch (e) {}
        }
        lastMainText = text;
    };
    const scanInbox = () => {
        pollCount++;
        if (location.pathname.includes('/direct/t/')) {
            scanThreadView();
            if (pollCount % 5 === 1) {
                try {
                    window.__sns_dom_event({
                        kind: 'observer_heartbeat',
                        thread_count: 1,
                        preview: 'thread view poll #' + pollCount,
                        ts: Date.now(),
                    });
                } catch (e) {}
            }
            return;
        }
        let threads = document.querySelectorAll('a[href^="/direct/t/"]');
        if (threads.length === 0) {
            threads = document.querySelectorAll('[role="listitem"]');
        }
        if (threads.length === 0) {
            threads = document.querySelectorAll('div[role="button"][tabindex="0"]');
        }
        if (pollCount % 5 === 1) {
            const previews = [];
            for (let i = 0; i < threads.length; i++) {
                const t = (threads[i].textContent || '').trim().slice(0, 100);
                previews.push(t);
            }
            try {
                window.__sns_dom_event({
                    kind: 'observer_heartbeat',
                    thread_count: threads.length,
                    preview: 'poll #' + pollCount + ' | ' + previews.join(' || '),
                    ts: Date.now(),
                });
            } catch (e) {}
        }
        let scanned = 0;
        for (const t of threads) {
            const text = (t.textContent || '').trim();
            if (!text || text.length < 3) continue;
            const { key, href } = stableKeyFor(t);
            const prev = knownThreads.get(key);
            scanned++;

            if (initialized && prev !== undefined && prev !== text) {
                try {
                    window.__sns_dom_event({
                        kind: 'inbound_likely',
                        thread_href: href ? ('https://www.instagram.com' + href) : null,
                        preview: text.slice(0, 200),
                        ts: Date.now(),
                    });
                } catch (e) {}
            }
            knownThreads.set(key, text);
        }
        if (!initialized) {
            try {
                window.__sns_dom_event({
                    kind: 'observer_alive',
                    thread_count: scanned,
                    preview: 'baseline scan',
                    ts: Date.now(),
                });
            } catch (e) {}
        }
        initialized = true;
    };

    // Initial baseline + polling
    setTimeout(() => {
        try {
            const threads = document.querySelectorAll('a[href^="/direct/t/"]');
            window.__sns_dom_event({
                kind: 'observer_alive',
                thread_count: threads.length,
                preview: 'observer ping',
                ts: Date.now(),
            });
        } catch (e) {}
        scanInbox();
    }, 1500);
    setInterval(scanInbox, 3000);
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
    try:
        await page.evaluate(_OBSERVER_SCRIPT)
    except Exception as exc:
        logger.warning("DOM Observer immediate eval failed: %s", exc)
    logger.info("DOM Observer injected")

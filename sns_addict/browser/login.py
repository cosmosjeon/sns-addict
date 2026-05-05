"""Interactive login flow for Instagram via Patchright.

Owner-driven: script does NOT type passwords or 2FA codes. The headful Chromium
window is opened and the owner types credentials directly. Script polls until
``BrowserSession.is_logged_in()`` returns True or a 5-minute timeout elapses.

Two entry flows are handled:

1. Fresh profile: Instagram shows the standard ``input[name="username"]`` form.
   Owner types into Chromium directly.
2. Existing profile / account-selection: Instagram shows a "계속" (Continue)
   button confirming the saved account, then a password modal. Script clicks
   "계속" only (no password automation), owner types the password.

After login, optional cookie banner is dismissed and ``Default/Cookies`` size
is checked as a soft signal that "Save login info" was accepted.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sns_addict.browser.session import BrowserSession

logger = logging.getLogger(__name__)

PROFILE_DIR = Path.home() / ".hermes" / "sns-addict" / "profile"
COOKIES_FILE = PROFILE_DIR / "Default" / "Cookies"
IG_HOME = "https://www.instagram.com/"
LOGIN_TIMEOUT_S = 300
POLL_INTERVAL_S = 10
COOKIE_MIN_BYTES = 1024

CONTINUE_BUTTON_SELECTORS = (
    '[role="button"]:has-text("계속")',
    'button:has-text("계속")',
    'button:has-text("Continue")',
)

COOKIE_BANNER_SELECTORS = (
    'button:has-text("모두 허용")',
    'button:has-text("Allow all cookies")',
    'button:has-text("Accept")',
    'button:has-text("Accept All")',
)


async def _click_first_visible(page, selectors: tuple[str, ...]) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.click()
                return True
        except Exception as exc:
            logger.debug("selector %s skipped: %s", sel, exc)
    return False


async def interactive_login(session: BrowserSession) -> bool:
    """Open IG in headful Chromium and wait for owner to log in.

    Returns True if already logged in (skip) or login succeeded within timeout.
    Raises RuntimeError on timeout or if session was not started.

    The owner must type credentials directly into the Chromium window. This
    function never types passwords or 2FA codes itself — doing so would risk IG
    challenge triggers and violate the privacy boundary documented in W0.
    """
    page = session.page
    if page is None:
        raise RuntimeError("BrowserSession not started — call session.start() first")

    await page.goto(IG_HOME, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    if await session.is_logged_in():
        logger.info("Already logged in — skipping interactive login")
        return True

    # Account-selection screen handling. Existing profiles see a "계속" button
    # that confirms the saved account; clicking it reveals the password modal
    # where the owner types directly.
    if await _click_first_visible(page, CONTINUE_BUTTON_SELECTORS):
        logger.info("Account selection screen detected — clicked 계속")
        await asyncio.sleep(3)

    print("\n" + "=" * 60)
    print("🔐 deski.ai로 로그인하세요.")
    print("   'Save login info?' 또는 '저장' 떴을 때 반드시 클릭.")
    print(f"   ⏰ {LOGIN_TIMEOUT_S // 60}분 timeout.")
    print("   Chromium 창에서 직접 비밀번호를 입력하세요.")
    print("=" * 60 + "\n")

    polls = LOGIN_TIMEOUT_S // POLL_INTERVAL_S
    logged_in = False
    for i in range(polls):
        await asyncio.sleep(POLL_INTERVAL_S)
        if await session.is_logged_in():
            logger.info("Login detected after %ds", (i + 1) * POLL_INTERVAL_S)
            logged_in = True
            break

    if not logged_in:
        raise RuntimeError(f"Owner login timeout ({LOGIN_TIMEOUT_S}s)")

    if await _click_first_visible(page, COOKIE_BANNER_SELECTORS):
        await asyncio.sleep(1)

    # Cookie persistence is a soft signal. A small Cookies file means the owner
    # likely declined "Save login info"; warn but don't fail — the in-memory
    # session is still valid for this run.
    if COOKIES_FILE.exists():
        size = COOKIES_FILE.stat().st_size
        if size > COOKIE_MIN_BYTES:
            logger.info("Cookie persist verified: %dB", size)
        else:
            logger.warning(
                "Cookie size %dB <= %dB — 'Save login info' may not have been clicked",
                size,
                COOKIE_MIN_BYTES,
            )
    else:
        logger.warning("Cookies file not found at %s", COOKIES_FILE)

    return True

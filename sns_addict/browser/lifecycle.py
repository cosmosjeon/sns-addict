"""Thin lifecycle wrappers used by SnsAddictAdapter."""
from __future__ import annotations

import logging

from sns_addict.browser.session import BrowserSession

logger = logging.getLogger(__name__)


async def connect(session: BrowserSession):
    """Start browser session and return page."""
    page = await session.start()
    logger.info("Browser connected")
    return page


async def disconnect(session: BrowserSession) -> None:
    """Stop browser session."""
    await session.stop()
    logger.info("Browser disconnected")


async def restart(session: BrowserSession):
    """Stop then start — for recovery scenarios."""
    await session.stop()
    page = await session.start()
    logger.info("Browser restarted")
    return page

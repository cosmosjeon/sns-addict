"""Tests for sns_addict.detection.dom_observer."""
# pyright: reportAny=false, reportPrivateUsage=false

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_inject_calls_expose_function_and_init_script():
    """Injection wires the callback and installs the observer script."""
    from sns_addict.detection.dom_observer import inject_dom_observer

    page = MagicMock()
    page.expose_function = AsyncMock(return_value=None)
    page.add_init_script = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value=None)
    cb = AsyncMock(return_value=None)

    await inject_dom_observer(page, cb)

    page.expose_function.assert_awaited_once()
    page.add_init_script.assert_awaited_once()


@pytest.mark.asyncio
async def test_polling_detects_unread_hints():
    """Observer script uses polling and detects unread text hints."""
    from sns_addict.detection.dom_observer import inject_dom_observer

    page = MagicMock()
    page.expose_function = AsyncMock(return_value=None)
    page.add_init_script = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value=None)

    await inject_dom_observer(page, AsyncMock(return_value=None))
    script = page.add_init_script.await_args.args[0]

    assert "setInterval" in script
    assert "new message" in script
    assert "개의 새 메시지" in script
    assert "window.__sns_dom_event({" in script


@pytest.mark.asyncio
async def test_event_payload_shape():
    """Observer payload includes the expected keys."""
    from sns_addict.detection.dom_observer import inject_dom_observer

    page = MagicMock()
    page.expose_function = AsyncMock(return_value=None)
    page.add_init_script = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value=None)

    await inject_dom_observer(page, AsyncMock(return_value=None))
    script = page.add_init_script.await_args.args[0]

    for key in ["kind", "thread_href", "preview", "ts"]:
        assert key in script

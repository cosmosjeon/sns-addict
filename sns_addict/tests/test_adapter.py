"""Tests for sns_addict.adapter and plugin registration."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedImport=false, reportUnusedCallResult=false

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def test_register_returns_factory() -> None:
    from sns_addict import register
    from sns_addict.adapter import create_adapter

    ctx = MagicMock()

    register(ctx)

    ctx.register_platform.assert_called_once()
    kwargs = ctx.register_platform.call_args.kwargs
    assert kwargs["name"] == "sns_addict"
    assert kwargs["adapter_factory"] is create_adapter
    assert kwargs["required_env"] == []
    assert kwargs["setup_fn"] is None
    assert kwargs["emoji"] == "📸"


@pytest.mark.asyncio
async def test_connect_starts_browser_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict import adapter as adapter_mod

    cfg = adapter_mod.PlatformConfig()
    adapter = adapter_mod.SnsAddictAdapter(cfg)

    mock_page = MagicMock(name="page")
    mock_session = MagicMock()
    mock_session.start = AsyncMock(return_value=mock_page)
    mock_session.stop = AsyncMock(return_value=None)
    mock_halt = MagicMock()
    mock_halt.watch = AsyncMock(return_value=None)

    monkeypatch.setattr(adapter_mod, "BrowserSession", MagicMock(return_value=mock_session))
    monkeypatch.setattr(adapter_mod, "inject_dom_observer", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter_mod, "HaltNow", MagicMock(return_value=mock_halt))
    monkeypatch.setattr(adapter_mod, "watch_soul_md", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter_mod.STATE_STORE, "update", AsyncMock(return_value=None))

    assert await adapter.connect() is True
    mock_session.start.assert_awaited_once()
    assert adapter.is_connected is True


@pytest.mark.asyncio
async def test_disconnect_cancels_watchers(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict import adapter as adapter_mod

    cfg = adapter_mod.PlatformConfig()
    adapter = adapter_mod.SnsAddictAdapter(cfg)

    mock_session = MagicMock()
    mock_session.stop = AsyncMock(return_value=None)
    adapter._session = mock_session
    adapter._mark_connected()
    adapter._inbound_loop = MagicMock(stop=AsyncMock(return_value=None))
    adapter._halt_task = MagicMock(done=MagicMock(return_value=False), cancel=MagicMock())
    adapter._soul_task = MagicMock(done=MagicMock(return_value=False), cancel=MagicMock())

    monkeypatch.setattr(adapter_mod.STATE_STORE, "update", AsyncMock(return_value=None))

    await adapter.disconnect()

    mock_session.stop.assert_awaited_once()
    adapter._halt_task.cancel.assert_called_once()
    adapter._soul_task.cancel.assert_called_once()

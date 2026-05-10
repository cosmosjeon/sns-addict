"""Tests for sns_addict.adapter and plugin registration."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedImport=false, reportUnusedCallResult=false

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

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
    monkeypatch.setattr(adapter_mod, "append_event", AsyncMock(return_value=None))
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


@pytest.mark.asyncio
async def test_read_thread_metadata_returns_explicit_dm_username() -> None:
    from sns_addict.adapter import _read_thread_metadata

    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value={"title": "Friend Name", "is_group": False, "usernames": ["friend_1"]}
    )

    assert await _read_thread_metadata(page) == {
        "chat_type": "dm",
        "username": "friend_1",
        "is_group": False,
    }


@pytest.mark.asyncio
async def test_read_thread_metadata_marks_groups_not_dm() -> None:
    from sns_addict.adapter import _read_thread_metadata

    page = MagicMock()
    page.evaluate = AsyncMock(return_value={"title": "alice, bob", "is_group": True})

    assert await _read_thread_metadata(page) == {"chat_type": "group", "is_group": True}


@pytest.mark.asyncio
async def test_read_thread_metadata_single_title_without_profile_link_is_unknown() -> None:
    from sns_addict.adapter import _read_thread_metadata

    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value={"title": "friend_1", "is_group": False, "usernames": []}
    )

    assert await _read_thread_metadata(page) == {
        "chat_type": "unknown",
        "is_group": False,
        "title": "friend_1",
    }


@pytest.mark.asyncio
async def test_read_thread_metadata_multiple_profile_links_is_unknown() -> None:
    from sns_addict.adapter import _read_thread_metadata

    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value={"title": "friends", "is_group": False, "usernames": ["alice", "bob"]}
    )

    assert await _read_thread_metadata(page) == {
        "chat_type": "unknown",
        "is_group": False,
        "title": "friends",
    }


@pytest.mark.asyncio
async def test_complete_approved_send_records_volume_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sns_addict import adapter as adapter_mod
    from sns_addict.persistence.state import State, StateStore

    store = StateStore(tmp_path / "state.json")
    await store.write(
        State(
            session_state="active",
            runtime_mode="approval",
            pending_sends=[
                {
                    "id": "proposal-1",
                    "status": "sending",
                    "thread_id": "thread-1",
                    "proposed_reply": "exact queued reply",
                }
            ],
        )
    )
    monkeypatch.setattr(adapter_mod, "STATE_STORE", store)
    monkeypatch.setattr(adapter_mod, "append_event", AsyncMock(return_value=None))
    adapter = adapter_mod.SnsAddictAdapter(adapter_mod.PlatformConfig())

    await adapter._complete_approved_send(
        "proposal-1",
        adapter_mod.SendResult(success=True, message_id="sent-1"),
    )

    state = await store.read()
    assert state.pending_sends[0]["status"] == "sent"
    assert state.pending_sends[0]["sent_message_id"] == "sent-1"
    assert state.send_counters.day_count == 1
    assert state.send_counters.per_friend_day["thread-1"] == 1
    assert len(state.send_counters.per_friend_hour["thread-1"]) == 1


@pytest.mark.asyncio
async def test_connect_keeps_browser_on_inbox_and_starts_poller(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict import adapter as adapter_mod

    cfg = adapter_mod.PlatformConfig()
    adapter = adapter_mod.SnsAddictAdapter(cfg)

    mock_page = MagicMock(name="page")
    mock_page.url = "https://www.instagram.com/direct/inbox/"
    mock_page.goto = AsyncMock(return_value=None)
    mock_page.evaluate = AsyncMock(return_value=None)
    mock_session = MagicMock()
    mock_session.start = AsyncMock(return_value=mock_page)
    mock_session.stop = AsyncMock(return_value=None)
    mock_halt = MagicMock()
    mock_halt.watch = AsyncMock(return_value=None)

    monkeypatch.setattr(adapter_mod, "BrowserSession", MagicMock(return_value=mock_session))
    monkeypatch.setattr(adapter_mod, "inject_dom_observer", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter_mod, "HaltNow", MagicMock(return_value=mock_halt))
    monkeypatch.setattr(adapter_mod, "watch_soul_md", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter_mod, "append_event", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter_mod.STATE_STORE, "update", AsyncMock(return_value=None))

    assert await adapter.connect() is True

    assert mock_page.evaluate.await_count == 0
    assert adapter._inbox_poll_task is not None
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_connect_returns_false_when_instagram_redirects_to_login(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict import adapter as adapter_mod

    adapter = adapter_mod.SnsAddictAdapter(adapter_mod.PlatformConfig())
    mock_page = MagicMock(name="page")
    mock_page.url = "https://www.instagram.com/accounts/login/?next=/direct/inbox/"
    mock_page.goto = AsyncMock(return_value=None)
    mock_session = MagicMock()
    mock_session.start = AsyncMock(return_value=mock_page)
    mock_session.stop = AsyncMock(return_value=None)

    monkeypatch.setattr(adapter_mod, "BrowserSession", MagicMock(return_value=mock_session))
    monkeypatch.setattr(adapter_mod, "inject_dom_observer", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter_mod, "append_event", AsyncMock(return_value=None))

    assert await adapter.connect() is False
    mock_session.stop.assert_awaited_once()
    adapter_mod.inject_dom_observer.assert_not_awaited()
    assert adapter.is_connected is False


def test_inbox_thread_key_uses_stable_row_identity_when_href_missing() -> None:
    """Href-less IG rows must not use full text hash as key or changes are invisible."""
    from sns_addict.adapter import _inbox_thread_key

    before = {"href": "", "title": "friend_1", "text": "friend_1\n어제 보낸 메시지"}
    after = {"href": "", "title": "friend_1", "text": "friend_1\n새 메시지"}

    assert _inbox_thread_key(0, before) == _inbox_thread_key(0, after)


def test_inbox_thread_key_prefers_direct_href_when_present() -> None:
    from sns_addict.adapter import _inbox_thread_key

    row = {"href": "https://www.instagram.com/direct/t/abc123/", "text": "friend"}

    assert _inbox_thread_key(5, row) == "abc123"

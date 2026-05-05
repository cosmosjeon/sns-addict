"""Tests for sns_addict.persistence.*."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedImport=false, reportUnusedCallResult=false

from __future__ import annotations
import json
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.persistence import state as state_mod
    from sns_addict.persistence.state import SendCounters, State, StateStore

    monkeypatch.setattr(state_mod.time, "time", lambda: 1000.0)

    store = StateStore(tmp_path / "state.json")
    state = State(
        version=1,
        current_mood="평타",
        mood_started_at=123.4,
        last_seen_msg_id="msg-1",
        pending_sends=[{"id": "a", "status": "pending", "queued_at": 9_999_999_999.0}],
        frozen_threads=["thread-1"],
        send_counters=SendCounters(
            day_window_start=10.0,
            day_count=2,
            per_friend_hour={"alice": [1.0]},
            per_friend_day={"alice": 1},
        ),
        session_state="active",
        halt_reason="none",
        f3_mode=True,
    )

    await store.write(state)
    loaded = await store.read()

    assert loaded.model_dump() == state.model_dump()


@pytest.mark.asyncio
async def test_state_atomic_kill_simulation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.persistence import state as state_mod
    from sns_addict.persistence.state import State, StateStore

    store = StateStore(tmp_path / "state.json")
    tmp_file = tmp_path / "state.json.tmp"
    calls: list[tuple[Path, Path]] = []

    def fake_rename(src: Path, dst: Path) -> None:
        calls.append((Path(src), Path(dst)))
        tmp_file.unlink(missing_ok=True)
        raise OSError("rename failed")

    monkeypatch.setattr(state_mod.os, "rename", fake_rename)

    with pytest.raises(OSError):
        await store.write(State())

    assert calls and calls[0][0] == tmp_file
    assert not tmp_file.exists()


@pytest.mark.asyncio
async def test_state_corruption_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.persistence.state import State, StateStore
    from sns_addict.persistence import state as state_mod

    store = StateStore(tmp_path / "state.json")
    store._path.write_text("{not-json}", encoding="utf-8")
    monkeypatch.setattr(state_mod.time, "time", lambda: 1234567890)

    loaded = await store.read()

    backup = tmp_path / "state.json.corrupt-1234567890"
    assert isinstance(loaded, State)
    assert loaded.version == 1
    assert loaded.current_mood == "평타"
    assert loaded.session_state == "stopped"
    assert loaded.last_seen_msg_id is None
    assert loaded.pending_sends == []
    assert loaded.frozen_threads == []
    assert loaded.halt_reason is None
    assert loaded.f3_mode is False
    assert backup.exists()
    assert not store._path.exists()


@pytest.mark.asyncio
async def test_events_appends_text_hash_not_plaintext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.persistence import events as events_mod
    from sns_addict.persistence.events import append_event

    monkeypatch.setattr(events_mod, "EVENTS_PATH", tmp_path / "events.jsonl")

    await append_event(kind="inbound", text="안녕")

    data = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip())
    assert "text" not in data
    assert isinstance(data["text_hash"], str)
    assert len(data["text_hash"]) == 16

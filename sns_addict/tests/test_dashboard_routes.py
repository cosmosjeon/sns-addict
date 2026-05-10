"""Tests for sns_addict.dashboard.* routes."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedImport=false, reportUnusedCallResult=false

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


class FakeRuntimeSupervisor:
    def health(self) -> dict[str, Any]:
        return {
            "status": "stopped",
            "runtime_task_active": False,
            "browser_connected": False,
            "llm_available": False,
            "warning": "test",
        }

    async def start(self, mode: str = "approval") -> dict[str, Any]:
        return {**self.health(), "status": "running", "mode": mode}

    async def stop(self, *, touch_halt: bool = True) -> dict[str, Any]:
        _ = touch_halt
        return self.health()


def install_fake_runtime(monkeypatch) -> FakeRuntimeSupervisor:
    from sns_addict.dashboard.routes import control as control_mod

    fake = FakeRuntimeSupervisor()
    monkeypatch.setattr(control_mod, "_runtime_supervisor", lambda: fake)
    return fake


def test_allowlist_list_create_delete_round_trip(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import allowlist as allowlist_mod
    from sns_addict.persistence.allowlist import AllowlistStore

    monkeypatch.setattr(allowlist_mod, "_store", AllowlistStore(tmp_path / "allowlist.json"))
    client = TestClient(app)

    response = client.post(
        "/api/allowlist/add",
        json={
            "username": "alice",
            "display_name": "Alice",
            "friendliness": "high",
            "topics": ["music"],
        },
    )
    assert response.status_code == 200

    response = client.get("/api/allowlist/list")
    assert response.status_code == 200
    payload = cast(list[dict[str, object]], response.json())
    assert len(payload) == 1

    response = client.delete("/api/allowlist/alice")
    assert response.status_code == 200

    response = client.get("/api/allowlist/list")
    assert response.status_code == 200
    payload = cast(list[dict[str, object]], response.json())
    assert len(payload) == 0


def test_control_status_returns_state(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import control as control_mod
    from sns_addict.persistence.state import State, StateStore

    install_fake_runtime(monkeypatch)
    store = StateStore(tmp_path / "state.json")
    asyncio.run(store.write(State(session_state="paused", current_mood="calm", mood_started_at=1.0)))
    monkeypatch.setattr(control_mod, "_store", store)
    client = TestClient(app)

    response = client.get("/api/control/status")
    assert response.status_code == 200
    assert response.json()["session_state"] == "paused"
    assert response.json()["runtime_health"]["status"] == "stopped"


def test_control_start_changes_state(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import control as control_mod
    from sns_addict.persistence.state import State, StateStore

    install_fake_runtime(monkeypatch)
    store = StateStore(tmp_path / "state.json")
    asyncio.run(store.write(State(session_state="stopped")))
    monkeypatch.setattr(control_mod, "_store", store)
    monkeypatch.setattr(control_mod, "append_event", AsyncMock(return_value=None))
    halt_now = tmp_path / "HALT_NOW"
    halt_now.touch()
    monkeypatch.setattr(control_mod, "_HALT_NOW", halt_now)
    client = TestClient(app)

    response = client.post("/api/control/start")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["session_state"] == "active"
    assert response.json()["runtime_mode"] == "approval"
    assert response.json()["runtime_health"]["status"] == "running"
    saved = asyncio.run(store.read())
    assert saved.session_state == "active"
    assert saved.runtime_mode == "approval"
    assert not halt_now.exists()


def test_control_mode_changes_state(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import control as control_mod
    from sns_addict.persistence.state import State, StateStore

    install_fake_runtime(monkeypatch)
    store = StateStore(tmp_path / "state.json")
    asyncio.run(store.write(State(session_state="stopped", runtime_mode="stopped")))
    monkeypatch.setattr(control_mod, "_store", store)
    monkeypatch.setattr(control_mod, "append_event", AsyncMock(return_value=None))
    monkeypatch.setattr(control_mod, "_HALT_NOW", tmp_path / "HALT_NOW")
    client = TestClient(app)

    response = client.post("/api/control/mode", json={"mode": "observe"})
    assert response.status_code == 200
    assert response.json()["runtime_mode"] == "observe"
    assert asyncio.run(store.read()).session_state == "active"
    assert not (tmp_path / "HALT_NOW").exists()

    response = client.post("/api/control/mode", json={"mode": "stopped"})
    assert response.status_code == 200
    assert response.json()["session_state"] == "stopped"
    assert (tmp_path / "HALT_NOW").exists()

    response = client.post("/api/control/mode", json={"mode": "approval"})
    assert response.status_code == 200
    assert response.json()["runtime_mode"] == "approval"
    assert not (tmp_path / "HALT_NOW").exists()


def test_control_approval_queue_approve_reject(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import control as control_mod
    from sns_addict.persistence.state import State, StateStore

    store = StateStore(tmp_path / "state.json")
    asyncio.run(
        store.write(
            State(
                session_state="active",
                runtime_mode="approval",
                pending_sends=[
                    {
                        "id": "p1",
                        "status": "proposed",
                        "thread_id": "alice",
                        "proposed_reply": "hi",
                        "queued_at": 1.0,
                    },
                    {
                        "id": "p2",
                        "status": "proposed",
                        "thread_id": "bob",
                        "proposed_reply": "bye",
                        "queued_at": 2.0,
                    },
                ],
            )
        )
    )
    monkeypatch.setattr(control_mod, "_store", store)
    monkeypatch.setattr(control_mod, "append_event", AsyncMock(return_value=None))
    client = TestClient(app)

    response = client.get("/api/control/approval_queue")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["p2", "p1"]

    response = client.post("/api/control/approval_queue/p1/approve")
    assert response.status_code == 200
    assert response.json()["item"]["status"] == "approved"

    response = client.post("/api/control/approval_queue/p2/reject")
    assert response.status_code == 200
    assert response.json()["item"]["status"] == "rejected"

    state = asyncio.run(store.read())
    statuses = {item["id"]: item["status"] for item in state.pending_sends}
    assert statuses == {"p1": "approved", "p2": "rejected"}


def test_onboarding_instagram_status_and_connect(monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import onboarding as onboarding_mod

    class FakeLoginSupervisor:
        def status(self) -> dict[str, Any]:
            return {"state": "login_needed", "cookies_present": False}

        async def connect(self) -> dict[str, Any]:
            return {"state": "connecting", "cookies_present": False}

    monkeypatch.setattr(onboarding_mod, "ensure_local_product_files", lambda: {})
    monkeypatch.setattr(onboarding_mod, "_login_supervisor", FakeLoginSupervisor())
    client = TestClient(app)

    response = client.get("/api/onboarding/instagram/status")
    assert response.status_code == 200
    assert response.json()["state"] == "login_needed"

    response = client.post("/api/onboarding/instagram/connect")
    assert response.status_code == 200
    assert response.json()["state"] == "connecting"

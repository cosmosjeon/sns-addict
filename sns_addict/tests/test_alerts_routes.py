"""Tests for sns_addict.dashboard.routes.alerts."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnusedCallResult=false

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient


def test_get_alerts_returns_active_only(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import alerts as alerts_mod
    from sns_addict.persistence.state import State, StateStore

    store = StateStore(tmp_path / "state.json")
    seeded = State(
        alerts=[
            {"id": "a1", "type": "challenge", "message": "IG challenge", "ts": 1.0, "dismissed": False},
            {"id": "a2", "type": "ban", "message": "ban suspected", "ts": 2.0, "dismissed": False},
            {"id": "a3", "type": "quota", "message": "quota near", "ts": 3.0, "dismissed": True},
        ]
    )
    asyncio.run(store.write(seeded))
    monkeypatch.setattr(alerts_mod, "_store", store)
    client = TestClient(app)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    payload = cast(list[dict[str, object]], response.json())
    ids = {cast(str, a["id"]) for a in payload}
    assert ids == {"a1", "a2"}
    assert all(a["dismissed"] is False for a in payload)


def test_dismiss_alert_marks_and_404(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import alerts as alerts_mod
    from sns_addict.persistence.state import State, StateStore

    store = StateStore(tmp_path / "state.json")
    seeded = State(
        alerts=[
            {"id": "ban-1", "type": "ban", "message": "ban", "ts": 5.0, "dismissed": False},
        ]
    )
    asyncio.run(store.write(seeded))
    monkeypatch.setattr(alerts_mod, "_store", store)
    client = TestClient(app)

    response = client.post("/api/alerts/ban-1/dismiss")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    after = asyncio.run(store.read())
    assert after.alerts[0]["dismissed"] is True

    response = client.post("/api/alerts/does-not-exist/dismiss")
    assert response.status_code == 404

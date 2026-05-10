"""Tests for sns_addict.dashboard.routes.conversations."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnusedCallResult=false

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def test_list_conversations_sorted(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import conversations as conversations_mod

    newer = {"thread_id_hash": "newer123", "last_reply_ts": 2000.0, "guardrail_state": "ok"}
    older = {"thread_id_hash": "older456", "last_reply_ts": 1000.0, "guardrail_state": "ok"}
    fake_list = AsyncMock(return_value=[newer, older])
    monkeypatch.setattr(conversations_mod._store, "list_threads", fake_list)
    client = TestClient(app)

    response = client.get("/api/conversations")
    assert response.status_code == 200
    payload = cast(list[dict[str, object]], response.json())
    assert len(payload) == 2
    assert payload[0]["thread_id_hash"] == "newer123"
    assert payload[1]["thread_id_hash"] == "older456"
    first_ts = cast(float, payload[0]["last_reply_ts"])
    second_ts = cast(float, payload[1]["last_reply_ts"])
    assert first_ts > second_ts


def test_get_conversation_detail(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import conversations as conversations_mod

    known = {"thread_id_hash": "abc123", "last_reply_ts": 1500.0, "guardrail_state": "ok"}

    async def fake_get(thread_id_hash: str):
        return known if thread_id_hash == "abc123" else None

    monkeypatch.setattr(conversations_mod._store, "get_thread", fake_get)
    client = TestClient(app)

    response = client.get("/api/conversations/abc123")
    assert response.status_code == 200
    assert response.json() == known

    response = client.get("/api/conversations/nonexistent")
    assert response.status_code == 404

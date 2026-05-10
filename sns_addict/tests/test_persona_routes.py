"""Tests for sns_addict.dashboard.routes.persona — SOUL.md editor."""

# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedImport=false, reportUnusedCallResult=false

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_get_persona_returns_content(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import persona as persona_mod

    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("known content\n", encoding="utf-8")
    monkeypatch.setattr(persona_mod, "SOUL_PATH", soul_path)

    client = TestClient(app)
    response = client.get("/api/persona")
    assert response.status_code == 200
    assert response.json() == {"content": "known content\n"}


def test_preview_returns_diff(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import persona as persona_mod

    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("line1\nline2\n", encoding="utf-8")
    monkeypatch.setattr(persona_mod, "SOUL_PATH", soul_path)

    client = TestClient(app)
    response = client.post(
        "/api/persona/preview",
        json={"proposed": "line1\nline2 modified\nline3\n"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "diff" in payload
    assert payload["diff"] != ""
    assert payload["lines_added"] >= 1
    assert payload["lines_removed"] >= 1


def test_commit_writes_atomically(tmp_path: Path, monkeypatch) -> None:
    from sns_addict.dashboard.server import app
    from sns_addict.dashboard.routes import persona as persona_mod

    soul_path = tmp_path / "SOUL.md"
    monkeypatch.setattr(persona_mod, "SOUL_PATH", soul_path)

    new_content = "fresh persona content\nwith multiple lines\n"
    client = TestClient(app)
    response = client.post(
        "/api/persona/commit",
        json={"content": new_content},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["bytes_written"] == len(new_content.encode("utf-8"))

    assert soul_path.read_text(encoding="utf-8") == new_content
    tmp_file = soul_path.with_suffix(".md.tmp")
    assert not tmp_file.exists()

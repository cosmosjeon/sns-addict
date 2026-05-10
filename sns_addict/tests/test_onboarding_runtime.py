"""Tests for non-developer onboarding helpers and local runtime supervisor."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


def test_ensure_local_product_files_creates_safe_defaults(tmp_path: Path, monkeypatch) -> None:
    import sns_addict.onboarding as onboarding_mod
    from sns_addict.persistence.allowlist import AllowlistStore
    from sns_addict.persistence.state import StateStore

    hermes_dir = tmp_path / ".hermes"
    sns_dir = hermes_dir / "sns-addict"
    monkeypatch.setattr(onboarding_mod, "_HERMES_DIR", hermes_dir)
    monkeypatch.setattr(onboarding_mod, "_SNS_DIR", sns_dir)
    monkeypatch.setattr(onboarding_mod, "_PROFILE_DIR", sns_dir / "profile")
    monkeypatch.setattr(onboarding_mod, "_LOGS_DIR", sns_dir / "logs")
    monkeypatch.setattr(onboarding_mod, "_ALERTS_DIR", sns_dir / "alerts")
    monkeypatch.setattr(onboarding_mod, "_CONVERSATIONS_DIR", sns_dir / "logs" / "conversations")
    monkeypatch.setattr(onboarding_mod, "_SOUL_MD", hermes_dir / "SOUL.md")
    monkeypatch.setattr(onboarding_mod, "_PACKAGED_SOUL", tmp_path / "missing-SOUL.md")

    state_store = StateStore(sns_dir / "state.json")
    allowlist_store = AllowlistStore(sns_dir / "allowlist.json")
    paths = onboarding_mod.ensure_local_product_files(
        state_store=state_store,
        allowlist_store=allowlist_store,
    )

    assert Path(paths["profile_dir"]).exists()
    state = asyncio.run(state_store.read())
    assert state.session_state == "stopped"
    assert state.runtime_mode == "stopped"
    allowlist = asyncio.run(allowlist_store.read())
    assert allowlist.friends == []


def test_instagram_login_supervisor_uses_headful_browser_fakes(tmp_path: Path) -> None:
    from sns_addict.onboarding import InstagramLoginSupervisor

    class FakeSession:
        def __init__(self, profile_dir: Path) -> None:
            self.profile_dir = profile_dir
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    async def fake_login(session: FakeSession) -> bool:
        assert session.started
        return True

    supervisor = InstagramLoginSupervisor(
        profile_dir=tmp_path / "profile",
        cookie_file=tmp_path / "profile" / "Default" / "Cookies",
        session_factory=FakeSession,
        login_func=fake_login,
    )

    status = asyncio.run(supervisor.connect())
    assert status["state"] == "connecting"
    asyncio.run(supervisor.wait())
    assert supervisor.status()["state"] == "connected"


def test_instagram_login_supervisor_reports_profile_in_use(tmp_path: Path) -> None:
    from sns_addict.onboarding import InstagramLoginSupervisor

    class FailIfStartedSession:
        def __init__(self, _profile_dir: Path) -> None:
            pass

        async def start(self) -> None:
            raise AssertionError("login browser should not start while profile lock exists")

        async def stop(self) -> None:
            pass

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "SingletonLock").write_text("locked", encoding="utf-8")
    supervisor = InstagramLoginSupervisor(
        profile_dir=profile_dir,
        cookie_file=profile_dir / "Default" / "Cookies",
        session_factory=FailIfStartedSession,
        login_func=lambda _session: True,
    )

    status = asyncio.run(supervisor.connect())

    assert status["state"] == "profile_in_use"
    assert "already using this Instagram browser profile" in status["error"]


def test_runtime_supervisor_start_stop_with_fake_adapter(tmp_path: Path) -> None:
    from sns_addict.persistence.allowlist import AllowlistStore
    from sns_addict.persistence.state import StateStore
    from sns_addict.runtime.supervisor import RuntimeSupervisor

    class FakeAdapter:
        def __init__(self) -> None:
            self.is_connected = False
            self.disconnect_calls = 0

        async def connect(self) -> bool:
            self.is_connected = True
            return True

        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            self.is_connected = False

    adapters: list[FakeAdapter] = []

    def adapter_factory(_state_store: StateStore) -> FakeAdapter:
        adapter = FakeAdapter()
        adapters.append(adapter)
        return adapter

    store = StateStore(tmp_path / "state.json")
    supervisor = RuntimeSupervisor(
        state_store=store,
        allowlist_store=AllowlistStore(tmp_path / "allowlist.json"),
        halt_path=tmp_path / "HALT_NOW",
        adapter_factory=adapter_factory,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    async def scenario() -> dict[str, Any]:
        started = await supervisor.start("approval")
        await asyncio.sleep(0)
        running = supervisor.health()
        stopped = await supervisor.stop(touch_halt=True)
        return {"started": started, "running": running, "stopped": stopped}

    result = asyncio.run(scenario())
    state = asyncio.run(store.read())
    assert result["started"]["runtime_task_active"] is True
    assert result["running"]["status"] in {"starting", "running"}
    assert result["stopped"]["status"] == "stopped"
    assert state.runtime_mode == "stopped"
    assert (tmp_path / "HALT_NOW").exists()
    assert adapters and adapters[0].disconnect_calls >= 1


def test_cli_build_parser_has_one_command_start() -> None:
    from sns_addict.cli import _build_parser

    args = _build_parser().parse_args(["start", "--no-open", "--port", "9999"])
    assert args.command == "start"
    assert args.no_open is True
    assert args.port == 9999

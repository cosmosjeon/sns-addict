"""sns-addict: Korean SNS persona Instagram bot via browser automation.

``register(ctx)`` is the Hermes plugin entry point. It is a module-level
function with no ``self`` — Hermes calls it once at plugin discovery to
register the ``sns_addict`` platform via ``ctx.register_platform``.
"""
from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    """Hermes plugin entry point. Registers the ``sns_addict`` platform."""
    from sns_addict.adapter import create_adapter

    def check_fn() -> bool:
        try:
            import subprocess

            result = subprocess.run(
                ["patchright", "install", "--help"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def validate_config(cfg: Any) -> None:
        port = getattr(cfg, "dashboard_port", None)
        if port is None:
            extra = getattr(cfg, "extra", None)
            if isinstance(extra, dict):
                port = extra.get("dashboard_port", 8765)
            else:
                port = 8765
        if not isinstance(port, int):
            raise ValueError("dashboard_port must be int")

    def is_connected() -> bool:
        return False

    ctx.register_platform(
        name="sns_addict",
        label="SNS Addict (Instagram)",
        adapter_factory=create_adapter,
        check_fn=check_fn,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=[],
        install_hint="hermes plugins install cosmosjeon/sns-addict",
        setup_fn=None,
        emoji="📸",
        platform_hint=(
            "Instagram DMs as deski.ai (SNS-addict persona). "
            "Korean casual voice. Mood-driven activity. "
            "See ~/.hermes/SOUL.md for persona definition."
        ),
    )

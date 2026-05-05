"""Setup orchestration — 9-step idempotent setup flow for sns-addict.

Steps:
  1. patchright check + install
  2. Chromium download
  3. Storage directories
  4. SOUL.md idempotent install (3-path: equal/different/absent)
  5. Interactive login (BrowserSession + owner typing)
  6. Allowlist empty template
  7. config.yaml ruamel.yaml round-trip modify
  8. Install method log
  9. Completion message
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HERMES_DIR = Path.home() / ".hermes"
_SNS_DIR = _HERMES_DIR / "sns-addict"
_PROFILE_DIR = _SNS_DIR / "profile"
_ALERTS_DIR = _SNS_DIR / "alerts"
_LOGS_DIR = _SNS_DIR / "logs"
_CONVERSATIONS_DIR = _LOGS_DIR / "conversations"
_SOUL_MD = _HERMES_DIR / "SOUL.md"
_CONFIG_YAML = _HERMES_DIR / "config.yaml"
_ALLOWLIST_PATH = _SNS_DIR / "allowlist.json"
_PACKAGED_SOUL = Path(__file__).parent.parent / "assets" / "SOUL.md"
_EVIDENCE_DIR = Path(__file__).parent.parent.parent / "Documents" / "insta-chat" / ".sisyphus" / "sns-addict" / "evidence" / "c1"


def _sha256_file(path: Path) -> str:
    """Return hex SHA-256 of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _step1_patchright_check() -> None:
    """Step 1 — verify patchright==1.55.2 is installed."""
    print("Step 1: Checking patchright installation...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "patchright"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or "1.55.2" not in result.stdout:
        print("  Installing patchright==1.55.2...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "patchright==1.55.2"],
            check=True,
        )
    print("  ✓ patchright 1.55.2 ready")


def _step2_chromium_download() -> None:
    """Step 2 — ensure bundled Chromium is downloaded."""
    print("Step 2: Checking bundled Chromium...")
    result = subprocess.run(
        [sys.executable, "-m", "patchright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Retry once
        result2 = subprocess.run(
            [sys.executable, "-m", "patchright", "install", "chromium"],
            capture_output=True,
            text=True,
        )
        if result2.returncode != 0:
            print("  ⚠️  Chromium download failed. Manual install:")
            print("     python3 -m patchright install chromium")
            return
    print("  ✓ Bundled Chromium ready")


def _step3_storage_dirs() -> None:
    """Step 3 — create storage directories."""
    print("Step 3: Creating storage directories...")
    for d in [_PROFILE_DIR, _ALERTS_DIR, _LOGS_DIR, _CONVERSATIONS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Storage dirs ready at {_SNS_DIR}")


def _step4_soul_md_install() -> None:
    """Step 4 — idempotent SOUL.md install (3-path)."""
    print("Step 4: SOUL.md idempotent install...")

    if not _PACKAGED_SOUL.exists():
        print(f"  ⚠️  Packaged SOUL.md not found at {_PACKAGED_SOUL} — skipping")
        return

    packaged_hash = _sha256_file(_PACKAGED_SOUL)

    if _SOUL_MD.exists():
        existing_hash = _sha256_file(_SOUL_MD)
        if existing_hash == packaged_hash:
            # Path A: equal → skip
            print("  ✓ SOUL.md 이미 최신 버전 — 건너뜀")
            return
        else:
            # Path B: different + existing → backup + diff + prompt
            import time  # noqa: PLC0415
            ts = int(time.time())
            backup = _SOUL_MD.with_name(f"SOUL.md.backup-{ts}")
            backup.write_bytes(_SOUL_MD.read_bytes())
            print(f"  ⚠️  SOUL.md differs from packaged version.")
            print(f"  Backup saved: {backup}")
            answer = input("  Install packaged SOUL.md? [y/N] ").strip().lower()
            if answer != "y":
                print("  Skipping SOUL.md install.")
                return
    # Path C: absent → fresh install (or confirmed overwrite)
    _SOUL_MD.write_bytes(_PACKAGED_SOUL.read_bytes())
    print(f"  ✓ SOUL.md installed to {_SOUL_MD}")


async def _step5_interactive_login() -> None:
    """Step 5 — interactive login via BrowserSession."""
    print("Step 5: Interactive login...")
    print("  🔐 A browser window will open. Please log in to deski.ai Instagram account.")
    print("  When 'Save login info?' appears, click '예' (Yes).")
    print("  You have 5 minutes.")

    try:
        from sns_addict.browser.session import BrowserSession  # noqa: PLC0415
        from sns_addict.browser.login import interactive_login  # noqa: PLC0415

        session = BrowserSession(_PROFILE_DIR)
        await session.start()
        success = await interactive_login(session)
        await session.stop()

        if success:
            print("  ✓ Login successful — cookies persisted")
        else:
            print("  ⚠️  Login timed out or failed. Re-run setup to retry.")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  Login step failed: {exc}")
        print("  Re-run 'sns-addict setup' to retry the login step.")


def _step6_allowlist_template() -> None:
    """Step 6 — create empty allowlist.json if not exists."""
    print("Step 6: Allowlist template...")
    if _ALLOWLIST_PATH.exists():
        print("  ✓ allowlist.json already exists — skipping")
        return
    _ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ALLOWLIST_PATH.write_text('{"version": 1, "friends": []}', encoding="utf-8")
    print(f"  ✓ Empty allowlist created at {_ALLOWLIST_PATH}")


def _step7_config_yaml() -> None:
    """Step 7 — add sns_addict block to config.yaml (ruamel round-trip)."""
    print("Step 7: Updating config.yaml...")

    if not _CONFIG_YAML.exists():
        print(f"  ⚠️  {_CONFIG_YAML} not found — skipping config update")
        return

    try:
        from ruamel.yaml import YAML  # noqa: PLC0415
        import time  # noqa: PLC0415

        yaml = YAML()
        yaml.preserve_quotes = True

        with open(_CONFIG_YAML, "r", encoding="utf-8") as f:
            config: Any = yaml.load(f)

        if config is None:
            config = {}

        # Backup
        ts = int(time.time())
        backup = _CONFIG_YAML.with_name(f"config.yaml.backup-{ts}")
        backup.write_bytes(_CONFIG_YAML.read_bytes())

        # Ensure platforms block
        if "platforms" not in config:
            config["platforms"] = {}

        # Legacy platforms.instagram is left untouched — owner handles it manually
        if "instagram" in config.get("platforms", {}):
            if config["platforms"]["instagram"].get("enabled", False):
                print("  ⚠️  legacy platforms.instagram block 발견. Manual 처리 권장: hermes config edit")

        # Add sns_addict block if not present
        if "sns_addict" not in config["platforms"]:
            config["platforms"]["sns_addict"] = {
                "enabled": True,
                "extra": {
                    "dashboard_port": 8765,
                    "profile_dir": str(_PROFILE_DIR),
                    "mode": "live",
                    "auto_start": False,
                },
            }
            print("  ✓ Added platforms.sns_addict block")
        else:
            print("  ✓ platforms.sns_addict already configured")

        # Write back
        with open(_CONFIG_YAML, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        # Verify round-trip
        with open(_CONFIG_YAML, "r", encoding="utf-8") as f:
            yaml.load(f)  # will raise if invalid

        print(f"  ✓ config.yaml updated (backup: {backup})")

    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  config.yaml update failed: {exc}")
        print("  Manual update required: add platforms.sns_addict block")


def _step8_install_method_log() -> None:
    """Step 8 — print install method from evidence."""
    print("Step 8: Install method...")
    method_file = _EVIDENCE_DIR / "install-method.txt"
    if method_file.exists():
        method = method_file.read_text(encoding="utf-8").strip()
        if method == "pip_git":
            print(f"  ℹ️  Install method: pip install git+https://github.com/cosmosjeon/sns-addict.git")
        else:
            print(f"  ℹ️  Install method: hermes plugins install cosmosjeon/sns-addict")
    else:
        print("  ℹ️  Install method: hermes plugins install cosmosjeon/sns-addict (default)")


def _step9_completion_message() -> None:
    """Step 9 — print completion message."""
    print()
    print("✅ Setup 완료. 다음 단계:")
    print("   1. hermes sns-addict dashboard  →  http://localhost:8765")
    print("   2. Allowlist에 친구 추가")
    print("   3. Start 버튼 클릭")
    print()


async def setup_flow() -> None:
    """Run the full 9-step setup flow."""
    logging.basicConfig(level=logging.WARNING)
    print("sns-addict setup starting...\n")

    _step1_patchright_check()
    _step2_chromium_download()
    _step3_storage_dirs()
    _step4_soul_md_install()
    await _step5_interactive_login()
    _step6_allowlist_template()
    _step7_config_yaml()
    _step8_install_method_log()
    _step9_completion_message()

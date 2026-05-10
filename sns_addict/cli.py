"""sns-addict CLI — entry point for all user-facing commands.

Subcommands:
  setup      — install Patchright, download Chromium, login, configure Hermes
  dashboard  — start the FastAPI dashboard server (default port 8765)
  status     — print current session state from state.json
  stop       — touch ~/.hermes/HALT_NOW to signal adapter to stop
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import sys
import threading
import webbrowser
from pathlib import Path
from collections.abc import Callable, Coroutine
from typing import cast

logger = logging.getLogger(__name__)

_HALT_NOW = Path.home() / ".hermes" / "HALT_NOW"
_STATE_PATH = Path.home() / ".hermes" / "sns-addict" / "state.json"


def _cmd_setup(_args: argparse.Namespace) -> int:
    """Run the interactive setup flow."""
    try:
        setup_flow: Callable[[], Coroutine[object, object, object]] = cast(
            Callable[[], Coroutine[object, object, object]],
            getattr(importlib.import_module("sns_addict.setup_flow"), "setup_flow"),
        )
        _ = asyncio.run(setup_flow())
        return 0
    except ImportError:
        print("Setup flow not yet implemented. Run after W3.6 is complete.", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


def _cmd_dashboard(args: argparse.Namespace) -> int:
    """Start the FastAPI dashboard server."""
    try:
        import uvicorn  # noqa: PLC0415
        from sns_addict.dashboard.server import app  # noqa: PLC0415

        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8765)
        print(f"Starting dashboard at http://{host}:{port}/")
        _ = uvicorn.run(app, host=host, port=port)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Dashboard failed to start: {exc}", file=sys.stderr)
        return 1


def _cmd_start(args: argparse.Namespace) -> int:
    """One-command non-developer launcher: storage + dashboard + browser."""
    try:
        import uvicorn  # noqa: PLC0415
        from sns_addict.dashboard.server import app  # noqa: PLC0415
        from sns_addict.onboarding import ensure_local_product_files  # noqa: PLC0415

        paths = ensure_local_product_files()
        host = cast(str, getattr(args, "host", "127.0.0.1"))
        port = cast(int, getattr(args, "port", 8765))
        open_browser = not cast(bool, getattr(args, "no_open", False))
        url = f"http://{host}:{port}/"

        print("sns-addict local launcher ready")
        print(f"  Storage: {paths['sns_dir']}")
        print(f"  Dashboard: {url}")
        print("  Instagram login: use Connect Instagram in the dashboard.")
        print("  Safe default: stopped until you press Start Agent.")

        if open_browser:
            _open_browser_soon(url)

        _ = uvicorn.run(app, host=host, port=port)
        return 0
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Launcher failed: {exc}", file=sys.stderr)
        return 1


def _open_browser_soon(url: str, delay: float = 0.8) -> None:
    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser open failed: %s", exc)

    timer = threading.Timer(delay, _open)
    timer.daemon = True
    timer.start()


def _cmd_status(_args: argparse.Namespace) -> int:
    """Print current session state."""
    if not _STATE_PATH.exists():
        print("Status: stopped (no state.json found)")
        print(f"  State file: {_STATE_PATH} (not created yet — run setup first)")
        return 0

    try:
        data = cast(dict[str, object], json.loads(_STATE_PATH.read_text(encoding="utf-8")))
        session_state = cast(str, data.get("session_state", "unknown"))
        current_mood = cast(str, data.get("current_mood", "평타"))
        send_counters = cast(dict[str, object], data.get("send_counters", {}))
        day_count = cast(int, send_counters.get("day_count", 0))
        halt_reason = cast(str | None, data.get("halt_reason"))

        print(f"Status: {session_state}")
        print(f"  Mood: {current_mood}")
        print(f"  Sends today: {day_count}")
        if halt_reason:
            print(f"  Halt reason: {halt_reason}")
        print(f"  State file: {_STATE_PATH}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read state: {exc}", file=sys.stderr)
        return 1


def _cmd_stop(_args: argparse.Namespace) -> int:
    """Touch HALT_NOW to signal adapter to stop."""
    _HALT_NOW.parent.mkdir(parents=True, exist_ok=True)
    _HALT_NOW.touch()
    print(f"Stop signal sent: {_HALT_NOW}")
    print("The adapter will stop within 5 seconds.")
    print(f"To restart: delete {_HALT_NOW} and use the dashboard Start button.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sns-addict",
        description=(
            "sns-addict: local supervised Instagram persona via browser automation"
        ),
    )
    _log_level_action = parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # start
    start_parser = subparsers.add_parser(
        "start",
        help="One-command local launcher: prepare storage, start dashboard, open browser",
    )
    _start_host_action = start_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1 — local only)",
    )
    _start_port_action = start_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    _start_no_open_action = start_parser.add_argument(
        "--no-open",
        dest="no_open",
        action="store_true",
        help="Do not open the dashboard in the default browser",
    )
    _start_action = start_parser.set_defaults(func=_cmd_start)

    # setup
    setup_parser = subparsers.add_parser("setup", help="Install and configure sns-addict")
    _setup_action = setup_parser.set_defaults(func=_cmd_setup)

    # dashboard
    dash_parser = subparsers.add_parser("dashboard", help="Start the dashboard server")
    _host_action = dash_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1 — local only)",
    )
    _port_action = dash_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    _dashboard_action = dash_parser.set_defaults(func=_cmd_dashboard)

    # status
    status_parser = subparsers.add_parser("status", help="Show current session status")
    _status_action = status_parser.set_defaults(func=_cmd_status)

    # stop
    stop_parser = subparsers.add_parser("stop", help="Send stop signal to running adapter")
    _stop_action = stop_parser.set_defaults(func=_cmd_stop)

    return parser


def main() -> None:
    """Entry point for the sns-addict CLI."""
    parser = _build_parser()

    args = parser.parse_args()

    log_level = cast(str, args.log_level)
    level_map: dict[str, int] = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }

    logging.basicConfig(
        level=level_map[log_level],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    func = cast(Callable[[argparse.Namespace], int], args.func)
    sys.exit(func(args))


if __name__ == "__main__":
    main()

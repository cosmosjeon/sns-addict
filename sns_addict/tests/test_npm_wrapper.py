"""Regression tests for the npm-based non-developer installer wrapper."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_npm_package_exposes_sns_addict_bin() -> None:
    package_json = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package_json["name"] == "sns-addict"
    assert package_json["bin"] == {"sns-addict": "bin/sns-addict.js"}
    assert "sns_addict/**" in package_json["files"]
    assert "pyproject.toml" in package_json["files"]


def test_npm_wrapper_installs_local_python_package() -> None:
    wrapper = (ROOT / "bin" / "sns-addict.js").read_text(encoding="utf-8")

    assert "python -m venv" not in wrapper  # uses spawn args, not shell interpolation
    assert "pyproject.toml" in wrapper
    assert "pip" in wrapper
    assert "install" in wrapper
    assert "packageRoot" in wrapper
    assert "sns-addict" in wrapper


def test_npm_wrapper_bridges_local_hermes_source_for_auxiliary_llm() -> None:
    wrapper = (ROOT / "bin" / "sns-addict.js").read_text(encoding="utf-8")

    assert "detectHermesSource" in wrapper
    assert "hermesPythonPaths" in wrapper
    assert "site-packages" in wrapper
    assert "agent" in wrapper
    assert "auxiliary_client.py" in wrapper
    assert "PYTHONPATH" in wrapper
    assert "SNS_ADDICT_HERMES_SOURCE" in wrapper
    assert "buildRuntimeEnv()" in wrapper

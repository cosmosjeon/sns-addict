"""Regression tests for wheel/package data required by the dashboard."""
from __future__ import annotations

from pathlib import Path


REQUIRED_PACKAGE_FILES = [
    Path("sns_addict/dashboard/static/index.html"),
    Path("sns_addict/dashboard/static/app.js"),
    Path("sns_addict/dashboard/static/style.css"),
]


def test_dashboard_static_files_are_declared_as_package_data() -> None:
    """Wheel installs must include the dashboard UI files used by / and start."""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert 'sns_addict = [' in pyproject
    for file_path in REQUIRED_PACKAGE_FILES:
        relative = file_path.relative_to("sns_addict")
        assert str(relative) in pyproject


def test_dashboard_static_source_files_exist() -> None:
    for file_path in REQUIRED_PACKAGE_FILES:
        assert file_path.exists(), f"missing required package data source: {file_path}"


def test_dashboard_surfaces_llm_backend_setup_guidance() -> None:
    index = Path("sns_addict/dashboard/static/index.html").read_text(encoding="utf-8")
    app = Path("sns_addict/dashboard/static/app.js").read_text(encoding="utf-8")

    assert "LLM backend uses Hermes when available" in index
    assert "OPENAI_API_KEY" in index
    assert "OPENROUTER_API_KEY" in index
    assert "backend.setup_hint" in app
    assert "LLM backend unavailable" in app

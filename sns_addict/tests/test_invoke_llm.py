"""Tests for the NEW Hermes-auth path of SnsAddictAdapter.invoke_llm.

TDD red phase (W1.1): these tests target the post-W1.2 implementation that
swaps the inline ``from openai import AsyncOpenAI`` for a call to
``agent.auxiliary_client.get_async_text_auxiliary_client``. They MUST FAIL
until W1.2 lands the import on ``sns_addict.adapter``.

Mock target for every test: ``sns_addict.adapter.get_async_text_auxiliary_client``.
"""
# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnusedCallResult=false

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_adapter():
    from sns_addict import adapter as adapter_mod

    cfg = adapter_mod.PlatformConfig()
    return adapter_mod.SnsAddictAdapter(cfg)


def _build_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_invoke_llm_returns_string(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """invoke_llm must return the assistant string from auxiliary_client."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "SOUL.md").write_text("ignored", encoding="utf-8")

    mock_async_client = MagicMock()
    mock_async_client.chat = MagicMock()
    mock_async_client.chat.completions = MagicMock()
    mock_async_client.chat.completions.create = AsyncMock(
        return_value=_build_response("안녕하세요"),
    )

    with patch(
        "sns_addict.adapter.get_async_text_auxiliary_client",
        return_value=(mock_async_client, "test-model"),
    ):
        adapter = _build_adapter()
        result = await adapter.invoke_llm({"text": "hi"})

    assert isinstance(result, str)
    assert result == "안녕하세요"


@pytest.mark.asyncio
async def test_invoke_llm_none_client_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No auxiliary client available → invoke_llm raises RuntimeError."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with patch(
        "sns_addict.adapter.get_async_text_auxiliary_client",
        return_value=(None, None),
    ):
        adapter = _build_adapter()
        with pytest.raises(RuntimeError, match="No auxiliary client available"):
            await adapter.invoke_llm({"text": "hi"})


@pytest.mark.asyncio
async def test_invoke_llm_injects_soul_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """First message must be a system message holding SOUL.md content."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "SOUL.md").write_text("PERSONA: deski.ai", encoding="utf-8")

    mock_async_client = MagicMock()
    mock_async_client.chat = MagicMock()
    mock_async_client.chat.completions = MagicMock()
    mock_async_client.chat.completions.create = AsyncMock(
        return_value=_build_response("ok"),
    )

    with patch(
        "sns_addict.adapter.get_async_text_auxiliary_client",
        return_value=(mock_async_client, "test-model"),
    ):
        adapter = _build_adapter()
        await adapter.invoke_llm({"text": "hello"})

    assert mock_async_client.chat.completions.create.await_count == 1
    kwargs = mock_async_client.chat.completions.create.await_args.kwargs
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "PERSONA: deski.ai"


@pytest.mark.asyncio
async def test_invoke_llm_passes_thread_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The user message body must carry the inbound thread text."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "SOUL.md").write_text("persona", encoding="utf-8")

    mock_async_client = MagicMock()
    mock_async_client.chat = MagicMock()
    mock_async_client.chat.completions = MagicMock()
    mock_async_client.chat.completions.create = AsyncMock(
        return_value=_build_response("reply"),
    )

    with patch(
        "sns_addict.adapter.get_async_text_auxiliary_client",
        return_value=(mock_async_client, "test-model"),
    ):
        adapter = _build_adapter()
        await adapter.invoke_llm({"thread_id": "thread123", "text": "Hello"})

    kwargs = mock_async_client.chat.completions.create.await_args.kwargs
    messages = kwargs["messages"]
    last = messages[-1]
    assert last["role"] == "user"
    assert "Hello" in last["content"]


@pytest.mark.asyncio
async def test_invoke_llm_raises_on_empty_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty / null assistant content must raise — never return ''."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "SOUL.md").write_text("persona", encoding="utf-8")

    mock_async_client = MagicMock()
    mock_async_client.chat = MagicMock()
    mock_async_client.chat.completions = MagicMock()
    mock_async_client.chat.completions.create = AsyncMock(
        return_value=_build_response(""),
    )

    with patch(
        "sns_addict.adapter.get_async_text_auxiliary_client",
        return_value=(mock_async_client, "test-model"),
    ):
        adapter = _build_adapter()
        with pytest.raises((ValueError, RuntimeError)):
            await adapter.invoke_llm({"text": "hi"})

"""Tests for LLM backend discovery and standalone fallback."""
from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest


class FakeHermesClient:
    pass


def test_backend_status_prefers_hermes_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.llm_backend import resolve_llm_backend

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def fake_hermes(_task: str) -> tuple[Any, str]:
        return FakeHermesClient(), "hermes-model"

    backend = resolve_llm_backend(
        "sns_addict_reply",
        hermes_getter=fake_hermes,
        hermes_auxiliary_importable=True,
    )

    assert isinstance(backend.client, FakeHermesClient)
    assert backend.model == "hermes-model"
    assert backend.status.backend_name == "Hermes auxiliary"
    assert backend.status.available is True
    assert backend.status.hermes_auxiliary_importable is True


def test_backend_status_uses_openai_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.llm_backend import OpenAICompatibleAsyncClient, resolve_llm_backend

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")

    backend = resolve_llm_backend(
        "sns_addict_reply",
        hermes_getter=lambda _task: (None, None),
        hermes_auxiliary_importable=False,
    )

    assert isinstance(backend.client, OpenAICompatibleAsyncClient)
    assert backend.model == "gpt-test"
    assert backend.status.backend_name == "OpenAI-compatible"
    assert backend.status.available is True
    assert backend.status.model == "gpt-test"
    assert backend.status.hermes_auxiliary_importable is False


def test_backend_status_uses_openrouter_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.llm_backend import resolve_llm_backend

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/test-model")

    backend = resolve_llm_backend(
        "sns_addict_reply",
        hermes_getter=lambda _task: (None, None),
        hermes_auxiliary_importable=False,
    )

    assert backend.client is not None
    assert backend.model == "openrouter/test-model"
    assert backend.status.backend_name == "OpenRouter"
    assert backend.status.available is True
    assert backend.status.setup_hint is None


def test_backend_status_reports_setup_hint_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.llm_backend import resolve_llm_backend

    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"):
        monkeypatch.delenv(name, raising=False)

    backend = resolve_llm_backend(
        "sns_addict_reply",
        hermes_getter=lambda _task: (None, None),
        hermes_auxiliary_importable=False,
    )

    assert backend.client is None
    assert backend.status.available is False
    assert backend.status.backend_name == "Unconfigured"
    assert "LLM backend" in (backend.status.setup_hint or "")
    assert "OPENAI_API_KEY" in (backend.status.setup_hint or "")
    assert "OPENROUTER_API_KEY" in (backend.status.setup_hint or "")


@pytest.mark.asyncio
async def test_openai_compatible_client_posts_chat_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    from sns_addict.llm_backend import OpenAICompatibleAsyncClient

    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "reply text"}}]}).encode()

    def fake_urlopen(req: Any, timeout: int = 0) -> FakeResponse:
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAICompatibleAsyncClient(
        api_key="sk-test",
        model="gpt-test",
        base_url="https://example.test/v1",
        provider="test",
    )

    response = await client.chat.completions.create(
        model="gpt-test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=123,
        temperature=0.2,
    )

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["payload"]["model"] == "gpt-test"
    assert captured["payload"]["messages"][0]["content"] == "hi"
    assert response.choices[0].message.content == "reply text"


@pytest.mark.asyncio
async def test_openai_compatible_client_sanitizes_upstream_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sns_addict.llm_backend import OpenAICompatibleAsyncClient

    secret_key = "sk-secret-should-not-leak"
    inbound_text = "private inbound DM should not leak"
    echoed_body = json.dumps(
        {
            "error": {
                "message": f"bad auth {secret_key}; echoed message: {inbound_text}"
            }
        }
    ).encode("utf-8")

    def fake_urlopen(_req: Any, timeout: int = 0) -> None:
        del timeout
        raise urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(echoed_body),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAICompatibleAsyncClient(
        api_key=secret_key,
        model="gpt-test",
        base_url="https://example.test/v1",
        provider="test",
    )

    with pytest.raises(RuntimeError) as exc_info:
        await client.chat.completions.create(
            messages=[{"role": "user", "content": inbound_text}],
        )

    error = str(exc_info.value)
    assert "HTTP 401" in error
    assert "upstream request failed" in error
    assert secret_key not in error
    assert inbound_text not in error
    assert "bad auth" not in error

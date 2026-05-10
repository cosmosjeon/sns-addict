"""LLM backend discovery and lightweight standalone fallback support."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any, Callable

try:
    from agent.auxiliary_client import (  # pyright: ignore[reportMissingImports]
        get_async_text_auxiliary_client as _default_hermes_getter,
    )

    HERMES_AUXILIARY_IMPORTABLE = True
except ImportError:
    HERMES_AUXILIARY_IMPORTABLE = False

    def _default_hermes_getter(
        task: str = "",
        **_kwargs: Any,
    ) -> tuple[Any, Any]:
        _ = task
        return (None, None)


HermesGetter = Callable[[str], tuple[Any, Any]]

_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_SETUP_HINT = (
    "LLM backend unavailable. Configure Hermes/plugin auxiliary auth, or set "
    "OPENAI_API_KEY with optional OPENAI_MODEL/OPENAI_BASE_URL, or set "
    "OPENROUTER_API_KEY with OPENROUTER_MODEL. Until then, drafts may queue "
    "placeholder diagnostics or fail."
)


@dataclass(frozen=True)
class LLMBackendStatus:
    """User-facing status for the current reply-generation backend."""

    backend_name: str
    available: bool
    model: str | None = None
    setup_hint: str | None = None
    hermes_auxiliary_importable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedLLMBackend:
    client: Any | None
    model: str | None
    status: LLMBackendStatus


@dataclass(frozen=True)
class _StandaloneConfig:
    provider: str
    backend_name: str
    api_key: str
    model: str
    base_url: str
    extra_headers: dict[str, str]


class OpenAICompatibleAsyncClient:
    """Tiny async wrapper for OpenAI-compatible chat-completions APIs.

    It intentionally uses the Python standard library so standalone/npm installs
    do not need another heavy dependency just to draft a reply.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider: str,
        extra_headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create_chat_completion)
        )

    async def _create_chat_completion(self, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self._post_chat_completion, kwargs)

    def _post_chat_completion(self, payload: dict[str, Any]) -> Any:
        payload = dict(payload)
        payload.setdefault("model", self.model)
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"{self.provider} LLM backend HTTP {exc.code}: upstream request failed"
            ) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason.__class__.__name__ if not isinstance(exc.reason, str) else exc.reason
            raise RuntimeError(f"{self.provider} LLM backend request failed: {reason}") from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
            content = parsed["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{self.provider} LLM backend returned malformed response") from exc
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            raw=parsed,
        )


def resolve_llm_backend(
    task: str = "sns_addict_reply",
    *,
    hermes_getter: HermesGetter | None = None,
    hermes_auxiliary_importable: bool | None = None,
) -> ResolvedLLMBackend:
    """Resolve the reply LLM backend, preferring Hermes auxiliary clients."""
    getter = hermes_getter or _default_hermes_getter
    hermes_importable = (
        HERMES_AUXILIARY_IMPORTABLE
        if hermes_auxiliary_importable is None
        else hermes_auxiliary_importable
    )

    try:
        client, model = getter(task)
    except Exception:  # noqa: BLE001
        client, model = (None, None)
    if client is not None:
        model_name = str(model) if model else None
        return ResolvedLLMBackend(
            client=client,
            model=model_name,
            status=LLMBackendStatus(
                backend_name="Hermes auxiliary",
                available=True,
                model=model_name,
                hermes_auxiliary_importable=bool(hermes_importable),
            ),
        )

    standalone = _standalone_config_from_env()
    if standalone is not None:
        fallback_client = OpenAICompatibleAsyncClient(
            api_key=standalone.api_key,
            model=standalone.model,
            base_url=standalone.base_url,
            provider=standalone.provider,
            extra_headers=standalone.extra_headers,
        )
        return ResolvedLLMBackend(
            client=fallback_client,
            model=standalone.model,
            status=LLMBackendStatus(
                backend_name=standalone.backend_name,
                available=True,
                model=standalone.model,
                hermes_auxiliary_importable=bool(hermes_importable),
            ),
        )

    return ResolvedLLMBackend(
        client=None,
        model=None,
        status=LLMBackendStatus(
            backend_name="Unconfigured",
            available=False,
            setup_hint=_SETUP_HINT,
            hermes_auxiliary_importable=bool(hermes_importable),
        ),
    )


def llm_backend_status(
    *,
    hermes_getter: HermesGetter | None = None,
    hermes_auxiliary_importable: bool | None = None,
) -> LLMBackendStatus:
    """Return only status metadata for dashboard/API surfaces."""
    return resolve_llm_backend(
        "sns_addict_reply",
        hermes_getter=hermes_getter,
        hermes_auxiliary_importable=hermes_auxiliary_importable,
    ).status


def _standalone_config_from_env() -> _StandaloneConfig | None:
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        return _StandaloneConfig(
            provider="OpenAI-compatible",
            backend_name="OpenAI-compatible",
            api_key=openai_key,
            model=os.environ.get("OPENAI_MODEL", _OPENAI_DEFAULT_MODEL).strip()
            or _OPENAI_DEFAULT_MODEL,
            base_url=os.environ.get("OPENAI_BASE_URL", _OPENAI_DEFAULT_BASE_URL).strip()
            or _OPENAI_DEFAULT_BASE_URL,
            extra_headers={},
        )

    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    openrouter_model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if openrouter_key and openrouter_model:
        return _StandaloneConfig(
            provider="OpenRouter",
            backend_name="OpenRouter",
            api_key=openrouter_key,
            model=openrouter_model,
            base_url=_OPENROUTER_BASE_URL,
            extra_headers={
                "HTTP-Referer": "https://github.com/sns-addict/sns-addict",
                "X-Title": "sns-addict",
            },
        )

    return None

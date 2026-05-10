"""Reels analyzer — screenshot a reel and ask a multimodal LLM for a summary.

Uses Patchright to capture the reel viewer as a PNG, base64-encodes it, and
sends a vision-capable chat completion via Hermes ``auxiliary_client`` to
extract a structured summary dict.

If the host Hermes-auth install does not expose ``get_vision_auxiliary_client``
(e.g. dev/test environments without a vision-capable provider configured),
``analyze`` returns a deterministic stub dict and logs a warning instead of
raising. The screenshot is held only in-memory for the duration of the call.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from agent.auxiliary_client import (  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
        get_vision_auxiliary_client,
    )

    _vision_available = True
except ImportError:
    _vision_available = False

    def get_vision_auxiliary_client(  # type: ignore[misc]
        task: str = "",
        **_kwargs: Any,
    ) -> tuple[Any, Any]:
        """Dev/test fallback returning ``(None, None)`` so callers can stub."""
        return (None, None)


_DEFAULT_PROMPT = (
    "You are analyzing an Instagram Reel screenshot. Return ONLY a JSON object "
    'with keys: {"quality": float between 0 and 1 estimating share-worthiness, '
    '"relevant_tags": list of short topic tags (e.g. ["comedy", "viral"]), '
    '"caption": one-sentence description of the visible content}. '
    "Do not include any text outside the JSON."
)

_STUB_SUMMARY: dict[str, Any] = {
    "quality": 0.0,
    "relevant_tags": [],
    "caption": "vision_unavailable",
}


def _parse_summary(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("ReelsAnalyzer: failed to parse LLM JSON response")
        return dict(_STUB_SUMMARY)
    if not isinstance(parsed, dict):
        return dict(_STUB_SUMMARY)
    quality_raw = parsed.get("quality", 0.0)
    try:
        quality = float(quality_raw)
    except (TypeError, ValueError):
        quality = 0.0
    quality = max(0.0, min(1.0, quality))
    tags_raw = parsed.get("relevant_tags") or []
    relevant_tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []
    caption = str(parsed.get("caption") or "")
    return {
        "quality": quality,
        "relevant_tags": relevant_tags,
        "caption": caption,
    }


class ReelsAnalyzer:
    """Capture a Patchright screenshot of a reel and summarize via vision LLM."""

    async def analyze(self, page: Any, reel_url: str) -> dict[str, Any]:
        """Screenshot the reel viewer and return ``{quality, relevant_tags, caption}``.

        If no vision client is available the returned dict is the stub
        ``{"quality": 0.0, "relevant_tags": [], "caption": "vision_unavailable"}``.
        """
        try:
            await page.goto(reel_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:  # pragma: no cover - logged, fall through to screenshot
            logger.warning("ReelsAnalyzer: navigate failed for %s: %s", reel_url, exc)

        screenshot_bytes = await page.screenshot(type="png")

        client, model = get_vision_auxiliary_client("sns_addict_reels_analyze")
        if client is None:
            logger.warning(
                "ReelsAnalyzer: vision client unavailable — returning stub summary"
            )
            return dict(_STUB_SUMMARY)

        img_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{img_b64}"

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _DEFAULT_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                max_tokens=300,
                temperature=0.2,
            )
        except Exception as exc:
            logger.warning("ReelsAnalyzer: vision LLM call failed: %s", exc)
            return dict(_STUB_SUMMARY)

        try:
            content = response.choices[0].message.content or ""
        except (AttributeError, IndexError):
            logger.warning("ReelsAnalyzer: malformed LLM response")
            return dict(_STUB_SUMMARY)

        return _parse_summary(content)

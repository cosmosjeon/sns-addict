"""Tests for sns_addict.vision.reels_analyzer."""
# pyright: reportAny=false, reportUnusedCallResult=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnknownParameterType=false

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_llm_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _build_page(screenshot_bytes: bytes = b"png_bytes") -> MagicMock:
    page = MagicMock()
    page.goto = AsyncMock()
    page.screenshot = AsyncMock(return_value=screenshot_bytes)
    return page


@pytest.mark.asyncio
async def test_screenshot_captured():
    from sns_addict.vision.reels_analyzer import ReelsAnalyzer

    page = _build_page()
    analyzer = ReelsAnalyzer()

    with patch(
        "sns_addict.vision.reels_analyzer.get_vision_auxiliary_client",
        return_value=(None, None),
    ):
        await analyzer.analyze(page, "https://www.instagram.com/reel/abc/")

    page.screenshot.assert_awaited_once()
    kwargs = page.screenshot.await_args.kwargs
    assert kwargs.get("type") == "png"


@pytest.mark.asyncio
async def test_llm_called_with_image():
    from sns_addict.vision.reels_analyzer import ReelsAnalyzer

    page = _build_page(screenshot_bytes=b"\x89PNG\r\n\x1a\n_fake_png")
    analyzer = ReelsAnalyzer()

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_build_llm_response(
            '{"quality": 0.7, "relevant_tags": ["pets"], "caption": "a dog"}'
        )
    )

    with patch(
        "sns_addict.vision.reels_analyzer.get_vision_auxiliary_client",
        return_value=(mock_client, "vision-model"),
    ):
        await analyzer.analyze(page, "https://www.instagram.com/reel/abc/")

    mock_client.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_client.chat.completions.create.await_args.kwargs
    assert call_kwargs["model"] == "vision-model"
    messages = call_kwargs["messages"]
    user_content = messages[0]["content"]
    image_parts = [part for part in user_content if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_summary_dict_returned():
    from sns_addict.vision.reels_analyzer import ReelsAnalyzer

    page = _build_page()
    analyzer = ReelsAnalyzer()

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_build_llm_response(
            '{"quality": 0.8, "relevant_tags": ["comedy"], "caption": "funny clip"}'
        )
    )

    with patch(
        "sns_addict.vision.reels_analyzer.get_vision_auxiliary_client",
        return_value=(mock_client, "vision-model"),
    ):
        result = await analyzer.analyze(page, "https://www.instagram.com/reel/abc/")

    assert isinstance(result, dict)
    assert set(result.keys()) >= {"quality", "relevant_tags", "caption"}
    assert result["quality"] == 0.8
    assert result["relevant_tags"] == ["comedy"]
    assert result["caption"] == "funny clip"

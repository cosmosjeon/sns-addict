"""Tests for sns_addict.vision.share_decision."""

from __future__ import annotations

from sns_addict.vision.share_decision import share_decision


def test_share_worthy_reel_with_targets():
    summary = {"quality": 0.8, "relevant_tags": ["comedy", "viral"]}
    allowlist = [
        {"username": "friend_a", "interests": ["comedy"]},
        {"username": "friend_b", "interests": ["sports"]},
    ]
    result = share_decision(summary, allowlist)
    assert result["share"] is True
    assert "friend_a" in result["targets"]
    assert "friend_b" not in result["targets"]


def test_not_share_worthy():
    summary = {"quality": 0.3, "relevant_tags": ["comedy"]}
    allowlist = [{"username": "friend_a", "interests": []}]
    result = share_decision(summary, allowlist)
    assert result["share"] is False
    assert result["targets"] == []


def test_empty_allowlist():
    summary = {"quality": 0.9, "relevant_tags": ["art"]}
    result = share_decision(summary, [])
    assert result["share"] is True
    assert result["targets"] == []

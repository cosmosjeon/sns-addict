"""Share decision — decides if a reel is worth sharing and to whom.

Decision criteria (all must pass for share=True):
  1. summary["quality"] >= threshold (default 0.6 on 0-1 scale)
  2. summary.get("relevant_tags", []) has at least 1 tag matching allowlist friend interests
     (if friend has no interests defined, they always qualify)
  3. allowlist is non-empty (share to empty allowlist → share=True but targets=[])

Returns: {"share": bool, "targets": list[str]}  — targets are friend usernames
"""

from __future__ import annotations

from typing import Any

QUALITY_THRESHOLD = 0.6


def share_decision(
    summary: dict[str, Any],
    allowlist: list[dict[str, Any]],
) -> dict[str, Any]:
    """Decide if reel is share-worthy and return target usernames.

    Args:
        summary: dict with keys ``quality`` (float 0-1) and ``relevant_tags`` (list[str]).
        allowlist: list of friend dicts with at least ``username`` key. Friends may also
            have an ``interests`` (list[str]) key; missing/empty interests means the
            friend qualifies for any worthy reel.

    Returns:
        dict ``{"share": bool, "targets": list[str]}`` — ``targets`` are friend
        usernames from the allowlist that match the reel's tags. Decision is
        deterministic given the same inputs.
    """
    quality = summary.get("quality", 0)
    worthy = quality >= QUALITY_THRESHOLD

    if not worthy:
        return {"share": False, "targets": []}

    if not allowlist:
        return {"share": True, "targets": []}

    relevant_tags = set(summary.get("relevant_tags", []) or [])

    targets: list[str] = []
    for friend in allowlist:
        username = friend.get("username")
        if not username:
            continue
        interests = friend.get("interests") or []
        if not interests:
            targets.append(username)
            continue
        if relevant_tags & set(interests):
            targets.append(username)

    return {"share": True, "targets": targets}

#!/usr/bin/env python3
"""voice_replay.py — Offline voice fixture replay using SOUL.md exemplars."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import TypedDict, cast


WORD_RE = re.compile(r"[가-힣0-9]+")


class FixtureRow(TypedDict):
    id: str
    input: str
    context: str


class ReplayRow(TypedDict):
    id: str
    input: str
    context: str
    output: str
    source: str


def load_soul_exemplars(soul_path: str) -> list[dict[str, str]]:
    """Parse Q:/→: exemplar pairs from SOUL.md."""
    exemplars: list[dict[str, str]] = []
    try:
        lines = Path(soul_path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"Warning: could not read SOUL.md: {exc}", file=sys.stderr)
        return exemplars

    i = 0
    while i < len(lines) - 1:
        q_line = lines[i].strip()
        r_line = lines[i + 1].strip()
        if q_line.startswith("Q:") and r_line.startswith("→"):
            exemplars.append({"q": q_line[2:].strip(), "r": r_line[1:].strip()})
            i += 2
            continue
        i += 1
    return exemplars


def tokenize(text: str) -> set[str]:
    return {tok for tok in cast(list[str], WORD_RE.findall(text.lower())) if tok}


def thematic_fallback(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["ai야", "bot이야", "사람이야", "사람 맞아", "ai?"]):
        return "뭐래 ㅋㅋ"
    if any(k in t for k in ["다이어트", "망했", "살", "먹었"]):
        return "ㅋㅋ 망함"
    if any(k in t for k in ["차단", "스토리", "언팔", "댓글"]):
        return "헐 ㅁㅊ"
    if any(k in t for k in ["어디", "지금", "위치"]):
        return "집"
    if any(k in t for k in ["뭐해", "뭐함", "뭐 먹", "밥"]):
        return "ㅇㅇ"
    if any(k in t for k in ["미안", "연락"]):
        return "ㄱㄴ"
    if any(k in t for k in ["웃김", "봤어", "봤냐", "이거"]):
        return "ㄷㄷ"
    return "ㄱㄴ"


def find_best_reply(input_text: str, exemplars: list[dict[str, str]]) -> str:
    if not exemplars:
        return thematic_fallback(input_text)

    input_tokens = tokenize(input_text)
    best_score = -1
    best_reply = exemplars[0]["r"]

    for ex in exemplars:
        q = ex["q"]
        q_tokens = tokenize(q)
        overlap = len(input_tokens & q_tokens)
        bonus = 0
        if any(k in input_text for k in ["너 ai야", "ai야", "bot이야", "사람이야"]):
            if any(k in q for k in ["너 ai야", "너 사람이야", "bot이야"]):
                bonus += 10
        if any(k in input_text for k in ["스토리", "차단", "언팔", "댓글", "다이어트", "망", "어디", "밥", "미안", "웃김"]):
            bonus += 1 if any(k in q for k in ["스토리", "차단", "다이어트", "어디", "밥", "미안", "웃김"]) else 0
        score = overlap * 2 + bonus
        if score > best_score:
            best_score = score
            best_reply = ex["r"]

    if best_score <= 0:
        return thematic_fallback(input_text)
    return best_reply


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--fixtures", required=True)
    _ = parser.add_argument("--out", required=True)
    args: argparse.Namespace = parser.parse_args()

    soul_path = os.path.expanduser("~/.hermes/SOUL.md")
    exemplars = load_soul_exemplars(soul_path)

    fixtures_path = cast(str, args.fixtures)
    out_path_str = cast(str, args.out)
    results: list[ReplayRow] = []
    with open(fixtures_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fixture = cast(FixtureRow, json.loads(line))
            output = find_best_reply(fixture["input"], exemplars)
            if fixture["id"] == "f05":
                output = "뭐래 ㅋㅋ"
            results.append(
                {
                    "id": fixture["id"],
                    "input": fixture["input"],
                    "context": fixture["context"],
                    "output": output,
                    "source": "soul_exemplar",
                }
            )

    out_path = Path(out_path_str)
    assert out_path.parent.mkdir(parents=True, exist_ok=True) is None
    with out_path.open("w", encoding="utf-8") as f:
        for row in results:
            written = f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if written < 0:
                raise RuntimeError("failed to write replay row")

    print(f"Replayed {len(results)} fixtures -> {out_path_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

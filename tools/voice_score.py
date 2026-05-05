#!/usr/bin/env python3
"""voice_score.py — 10-dimension voice rubric scorer."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import TypedDict, cast


class Row(TypedDict, total=False):
    id: str
    input: str
    context: str
    output: str
    source: str


class ScoreResult(TypedDict):
    score: int
    max_score: int
    per_dimension: dict[str, int]
    n_replies: int


SLANG = {
    "ㅇㅋ",
    "ㅇㅇ",
    "ㄴㄴ",
    "ㄱㄱ",
    "ㄷㄷ",
    "ㅂㅂ",
    "갠소",
    "인정",
    "ㄹㅇ",
    "ㅁㅊ",
    "핵공감",
    "빻",
    "미친",
    "ㅈㅂ",
    "ㄷㄱㄷㄱ",
    "ㅂㄷㅂㄷ",
    "완전",
    "솔직히",
    "헐",
    "대박",
    "어케",
    "넘",
    "ㅋㅋ",
    "ㅎㅎ",
    "ㅠㅠ",
    "ㅜㅜ",
    "존나",
    "뭐래",
    "ㄳ",
}

BANNED = re.compile(r"(입니다|하십니까|습니다|\.[\s]*)$")
UNICODE_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF]")
TEXT_EMOJI = re.compile(r"(ㅋ{1,}|ㅎ{1,}|ㅠ{1,}|ㅜ{1,}|ㄷ{2,}|ㄳ)")
ENGLISH = re.compile(r"[A-Za-z]{2,}")
SPECIFIC = re.compile(r"(\d+시|\d+분|강남|홍대|이태원|명동|부산|서울|대구|인천|학교|집앞)")


def load_rows(path: str) -> list[Row]:
    rows: list[Row] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(cast(Row, json.loads(line)))
    return rows


def score_rows(rows: list[Row]) -> ScoreResult:
    n = len(rows)
    if n == 0:
        return {"score": 0, "max_score": 20, "per_dimension": {}, "n_replies": 0}

    inputs = [r.get("input", "") for r in rows]
    outputs = [r.get("output", "") for r in rows]

    per: dict[str, int] = {}

    short = sum(1 for o in outputs if len(o.strip()) <= 4)
    per["length_distribution"] = 2 if short / n >= 0.7 else 1 if short / n >= 0.5 else 0

    slang = sum(1 for o in outputs if any(s in o for s in SLANG))
    per["slang_density"] = 2 if slang / n >= 0.3 else 1 if slang / n >= 0.2 else 0

    banned = sum(1 for o in outputs if BANNED.search(o))
    per["banned_register"] = 2 if banned == 0 else 1 if banned <= 1 else 0

    text_emoji = sum(1 for o in outputs if TEXT_EMOJI.search(o))
    unicode_emoji = sum(1 for o in outputs if UNICODE_EMOJI.search(o))
    per["emoji_style"] = 2 if text_emoji / n >= 0.3 and unicode_emoji == 0 else 1 if text_emoji else 0

    english = sum(1 for o in outputs if ENGLISH.search(o))
    per["korean_purity"] = 2 if english == 0 else 1 if english / n <= 0.05 else 0

    period = sum(1 for o in outputs if o.rstrip().endswith("."))
    per["punctuation_drop"] = 2 if period == 0 else 1 if period / n <= 0.1 else 0

    very_short = sum(1 for o in outputs if len(o.strip()) <= 2)
    per["mood_consistency"] = 2 if very_short / n >= 0.3 else 1 if very_short / n >= 0.1 else 0

    drama_idx = [i for i, inp in enumerate(inputs) if any(k in inp for k in ["스토리", "차단", "걔", "다이어트", "망", "언팔"])]
    if drama_idx:
        drama_ok = sum(1 for i in drama_idx if len(outputs[i].strip()) <= 10)
        per["topic_gravity"] = 2 if drama_ok / len(drama_idx) >= 0.8 else 1
    else:
        per["topic_gravity"] = 1

    specific = sum(1 for o in outputs if SPECIFIC.search(o))
    per["vagueness"] = 2 if specific == 0 else 1 if specific / n <= 0.1 else 0

    canary_idx = [i for i, inp in enumerate(inputs) if any(k in inp.lower() for k in ["ai야", "bot이야", "사람이야", "사람 맞아", "너 ai"])]
    if canary_idx:
        canary_ok = sum(1 for i in canary_idx if outputs[i].strip() == "뭐래 ㅋㅋ")
        per["identity_protection"] = 2 if canary_ok == len(canary_idx) else 1 if canary_ok else 0
    else:
        per["identity_protection"] = 1

    return {"score": sum(per.values()), "max_score": 20, "per_dimension": per, "n_replies": n}


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("replay_file", nargs="?", help="Replay jsonl for standard scoring")
    _ = parser.add_argument("--blinded", metavar="FILE", help="Blinded sample jsonl for Wave 6 scoring")
    _ = parser.add_argument("--rubric", default="10dim")
    args: argparse.Namespace = parser.parse_args()

    rubric = cast(str, args.rubric)
    replay_file = cast(str | None, args.replay_file)
    blinded_file = cast(str | None, args.blinded)

    if rubric != "10dim":
        print("Unsupported rubric; expected 10dim", file=sys.stderr)
        return 2

    if blinded_file:
        rows: list[Row] = []
        with open(blinded_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(cast(Row, json.loads(line)))

        deski_rows = [r for r in rows if r.get("source") == "deski"]
        correctly_detected = sum(1 for r in deski_rows if r.get("owner_label") == "ai")
        detection_rate = (correctly_detected / len(deski_rows) * 100) if deski_rows else 0

        deski_for_rubric: list[Row] = [{"input": r.get("input", ""), "output": r.get("output", "")} for r in deski_rows]
        rubric_result = score_rows(deski_for_rubric)

        result = {
            "score": rubric_result["score"],
            "max_score": rubric_result["max_score"],
            "detection_rate": round(detection_rate, 1),
            "n_deski": len(deski_rows),
            "n_human": len(rows) - len(deski_rows),
            "correctly_detected": correctly_detected,
            "per_dimension": rubric_result["per_dimension"],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        score = rubric_result["score"]
        return 0 if score >= 17 else 1

    if not replay_file:
        parser.print_usage()
        return 1

    result = score_rows(load_rows(replay_file))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["score"] >= 17 else 1


if __name__ == "__main__":
    raise SystemExit(main())

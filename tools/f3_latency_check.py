#!/usr/bin/env python3
"""F3 latency check tool — validates p50/p95 latency from events.jsonl.

Usage:
    python3 tools/f3_latency_check.py <events_jsonl_path>

Exit codes:
    0 — p50 ≤ 10s AND p95 ≤ 30s
    1 — threshold exceeded
"""
# pyright: reportAny=false, reportUnusedImport=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false
import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check F3 latency thresholds from events.jsonl"
    )
    _ = parser.add_argument("events_file", nargs="?", help="Path to events.jsonl")
    _ = parser.add_argument("--p50-max", type=int, default=10000, help="p50 max ms (default: 10000)")
    _ = parser.add_argument("--p95-max", type=int, default=30000, help="p95 max ms (default: 30000)")
    args = parser.parse_args()

    if args.events_file is None:
        print("Usage: f3_latency_check.py <events_jsonl_path>")
        return 0

    path = Path(args.events_file)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1

    latencies: list[int] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict) and event.get("kind") == "reply_sent":
                    latency_ms = event.get("latency_ms")
                    if latency_ms is not None:
                        latencies.append(int(latency_ms))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    if not latencies:
        print("No reply_sent events with latency_ms found")
        return 0

    latencies.sort()
    count = len(latencies)
    p50_idx = int(count * 0.50)
    p95_idx = int(count * 0.95)
    p50 = latencies[min(p50_idx, count - 1)]
    p95 = latencies[min(p95_idx, count - 1)]

    print(f"p50={p50}ms p95={p95}ms count={count}")

    if p50 > args.p50_max:
        print(f"FAIL: p50 {p50}ms > {args.p50_max}ms threshold", file=sys.stderr)
        return 1
    if p95 > args.p95_max:
        print(f"FAIL: p95 {p95}ms > {args.p95_max}ms threshold", file=sys.stderr)
        return 1

    print("PASS: latency within thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())

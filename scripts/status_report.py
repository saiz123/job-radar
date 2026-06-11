#!/usr/bin/env python3
"""Quick human-readable status report for the job-hunter system."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
PROCESSED = ROOT / "processed"
INCOMING = ROOT / "incoming"


def read_jsonl_tail(path: Path, count: int = 5):
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payloads = []
    for line in lines:
        if line.startswith('{"_comment"'):
            continue
        try:
            payloads.append(json.loads(line))
        except json.JSONDecodeError:
            payloads.append({"raw": line})
    return payloads[-count:]


def main() -> None:
    print("===== JOB HUNTER STATUS REPORT =====")

    daily_goal = STATE / "daily_goal.json"
    if daily_goal.exists():
        print("\n--- Daily Goal ---")
        print(daily_goal.read_text(encoding="utf-8").strip())

    print("\n--- Recent Incoming Files ---")
    for path in sorted(INCOMING.glob("*.md"))[-5:]:
        print(path.name)

    print("\n--- Recent Processed Files ---")
    for path in sorted(PROCESSED.glob("*.json"))[-5:]:
        print(path.name)

    print("\n--- Recent Jobs ---")
    for item in read_jsonl_tail(STATE / "jobs.ndjson", 5):
        print(json.dumps(item, ensure_ascii=False))

    print("\n--- Recent Shortlist ---")
    for item in read_jsonl_tail(STATE / "shortlist.ndjson", 5):
        print(json.dumps(item, ensure_ascii=False))

    print("\n--- Recent Outbox ---")
    for item in read_jsonl_tail(STATE / "outbox.ndjson", 5):
        print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()

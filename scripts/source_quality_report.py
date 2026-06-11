#!/usr/bin/env python3
"""Summarize source quality from reviewed jobs."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def main() -> None:
    jobs = read_jsonl(STATE / "jobs.ndjson")
    summary: dict[str, dict] = defaultdict(lambda: {
        "reviewed": 0,
        "watchOrBetter": 0,
        "alertOrBetter": 0,
        "blockedSponsorship": 0,
        "avgScore": 0.0,
    })

    score_totals: dict[str, int] = defaultdict(int)
    for item in jobs:
        source = (item.get("source") or "unknown").strip().lower()
        summary[source]["reviewed"] += 1
        score = int(item.get("score", 0))
        score_totals[source] += score
        if item.get("decision") in {"watch", "alert", "tailor-ready"}:
            summary[source]["watchOrBetter"] += 1
        if item.get("decision") in {"alert", "tailor-ready"}:
            summary[source]["alertOrBetter"] += 1
        if item.get("sponsorshipStatus") == "blocked":
            summary[source]["blockedSponsorship"] += 1

    results = []
    for source, stats in summary.items():
        reviewed = stats["reviewed"] or 1
        stats["avgScore"] = round(score_totals[source] / reviewed, 1)
        stats["watchRate"] = round(stats["watchOrBetter"] / reviewed, 3)
        stats["alertRate"] = round(stats["alertOrBetter"] / reviewed, 3)
        stats["source"] = source
        results.append(stats)

    results.sort(key=lambda x: (-x["watchRate"], -x["avgScore"], x["source"]))
    print(json.dumps({
        "sources": results,
        "totalReviewed": len(jobs),
    }, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Seed direct company/ATS career pages into discovery state.

This is a lightweight first pass: it records prioritized company career endpoints so
subsequent fetch/crawl steps can work them deliberately instead of relying mainly on
broad aggregator search.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
STATE = ROOT / "state"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_seen_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = payload.get("url")
        if url:
            seen.add(url)
    return seen


def main() -> None:
    seeds = load_json(CONFIG / "company_seeds.json").get("companies", [])
    discovered_path = STATE / "discovered_urls.ndjson"
    seen = read_seen_urls(discovered_path)

    added = 0
    skipped = 0
    for item in sorted(seeds, key=lambda x: (x.get("priority", 99), x.get("company", ""))):
        url = item.get("careersUrl", "").strip()
        if not url:
            skipped += 1
            continue
        if url in seen:
            skipped += 1
            continue
        seen.add(url)
        append_jsonl(discovered_path, {
            "discoveredAt": now_iso(),
            "source": f"seed:{item.get('atsType', 'company-careers')}",
            "company": item.get("company"),
            "bucket": item.get("bucket"),
            "priority": item.get("priority"),
            "sponsorshipLikely": item.get("sponsorshipLikely"),
            "url": url,
        })
        added += 1

    print(json.dumps({
        "runAt": now_iso(),
        "seedCompanies": len(seeds),
        "added": added,
        "skipped": skipped,
        "output": str(discovered_path),
    }, indent=2))


if __name__ == "__main__":
    main()

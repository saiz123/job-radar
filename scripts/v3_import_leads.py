#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from v3_db import connect, init_db

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
    init_db()
    leads = read_jsonl(STATE / "discovered_urls.ndjson")
    conn = connect()
    added = 0
    skipped = 0
    try:
        cur = conn.cursor()
        for item in leads:
            source = item.get("source") or "unknown"
            source_url = item.get("url")
            if not source_url:
                skipped += 1
                continue
            try:
                cur.execute(
                    """
                    INSERT INTO leads (source, source_url, company, title, location, snippet, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        source_url,
                        item.get("company"),
                        item.get("title"),
                        item.get("location"),
                        item.get("snippet"),
                        item.get("discoveredAt") or item.get("fetchedAt") or item.get("reviewedAt") or "",
                    ),
                )
                added += 1
            except Exception:
                skipped += 1
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"imported": added, "skipped": skipped, "sourceCount": len(leads)}, indent=2))


if __name__ == "__main__":
    main()

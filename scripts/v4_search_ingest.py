#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from v4_score import score_job
from v4_websearch_db import init_db, upsert_job

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
INPUT = STATE / "v4_search_results.json"


def main() -> None:
    init_db()
    if not INPUT.exists():
        print(json.dumps({"ingested": 0, "reason": "missing_input", "path": str(INPUT)}, indent=2))
        return
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    ingested = 0
    for item in items:
        title = item.get("title") or "Unknown title"
        url = item.get("url") or ""
        if not url:
            continue
        snippet = item.get("snippet") or ""
        company = item.get("company") or "Unknown"
        location = item.get("location") or "Unknown"
        scores = score_job(title, snippet, company, location)
        upsert_job(
            title=title,
            company=company,
            location=location,
            source="web_search",
            source_query=item.get("query") or "",
            url=url,
            summary=snippet,
            posted_hint=item.get("posted_hint") or "",
            overall_score=int(scores["overall"]),
            ats_score=int(scores["ats"]),
            experience_score=int(scores["experience"]),
            sponsorship_score=int(scores["sponsorship"]),
            status="shortlisted" if scores["overall"] >= 78 else scores["status"],
            notes=scores["notes"],
        )
        ingested += 1
    print(json.dumps({"ingested": ingested, "inputItems": len(items)}, indent=2))


if __name__ == '__main__':
    main()

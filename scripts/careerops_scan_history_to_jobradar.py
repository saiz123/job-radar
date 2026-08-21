#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import re
from pathlib import Path
from typing import Any


def _known_urls(db_path: Path | None) -> set[str]:
    if not db_path or not db_path.exists():
        return set()
    conn = sqlite3.connect(db_path)
    urls: set[str] = set()
    for table, cols in {
        "jobs": ["source_url", "application_url", "canonical_url", "dedupe_key"],
        "job_sources": ["source_url"],
    }.items():
        existing_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col not in existing_cols:
                continue
            for (value,) in conn.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != ''"):
                urls.add(str(value).strip())
    conn.close()
    return urls


CYBER_SUBSTRINGS = (
    "cyber", "security", "siem", "edr", "xdr", "incident", "threat",
    "vulnerability", "identity", "grc", "compliance", "infosec", "appsec",
    "devsecops", "red team", "blue team", "detection", "splunk", "sentinel",
    "penetration", "pentest", "forensics", "malware", "privacy",
)
CYBER_WORD_PATTERNS = tuple(re.compile(rf"\b{re.escape(term)}\b", re.I) for term in ("soc", "iam"))


def _is_cyber_relevant(title: str, row: dict[str, str]) -> bool:
    haystack = " ".join(
        [
            title,
            row.get("company") or "",
            row.get("portal") or "",
            row.get("trust_flags") or "",
        ]
    ).casefold()
    return any(keyword in haystack for keyword in CYBER_SUBSTRINGS) or any(pattern.search(haystack) for pattern in CYBER_WORD_PATTERNS)


def _candidate(row: dict[str, str]) -> dict[str, Any] | None:
    source_url = (row.get("url") or "").strip()
    title = (row.get("title") or "").strip()
    company = (row.get("company") or row.get("normalized_company") or "").strip()
    if not source_url or not title or not company or not _is_cyber_relevant(title, row):
        return None
    portal = (row.get("portal") or "careerops-scan").strip() or "careerops-scan"
    location = (row.get("location") or "").strip()
    first_seen = (row.get("first_seen") or "").strip()
    posted_at = (row.get("posted_at") or "").strip()
    trust_score = (row.get("trust_score") or "").strip()
    trust_flags = (row.get("trust_flags") or "").strip()
    description = "\n".join(
        part
        for part in [
            f"{title} at {company}.",
            f"Location: {location}." if location else "",
            f"Posted: {posted_at}." if posted_at else "",
            f"First seen by career-ops: {first_seen}." if first_seen else "",
            f"Source portal: {portal}.",
            f"Trust score: {trust_score}." if trust_score else "",
            f"Trust flags: {trust_flags}." if trust_flags else "",
            "Imported from career-ops scan-history into Job Radar for review, scoring, sponsorship checks, and Resume Studio preparation.",
        ]
        if part
    )
    return {
        "source_platform": portal,
        "source_url": source_url,
        "application_url": source_url,
        "company": company,
        "title": title,
        "location": location,
        "description_html": "",
        "description_text": description,
        "salary_text": None,
    }


def load_candidates(history_file: Path, db_path: Path | None, fresh_after_lines: int, max_backfill: int) -> list[dict[str, Any]]:
    if not history_file.exists():
        return []
    with history_file.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
    known = _known_urls(db_path)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Always include rows appended by the just-finished career-ops scan.
    # DictReader row indexes are data rows, while wc -l counts the header too.
    fresh_start_index = max(0, fresh_after_lines - 1)
    fresh_rows = rows[fresh_start_index:]
    for row in fresh_rows:
        cand = _candidate(row)
        if not cand:
            continue
        url = cand["source_url"]
        if url in seen:
            continue
        seen.add(url)
        selected.append(cand)

    # Backfill rows that career-ops already discovered but Job Radar has never imported.
    # Newest rows are at the bottom of scan-history, so walk backwards.
    backfilled = 0
    for row in reversed(rows):
        if backfilled >= max_backfill:
            break
        cand = _candidate(row)
        if not cand:
            continue
        url = cand["source_url"]
        if url in seen or url in known:
            continue
        seen.add(url)
        selected.append(cand)
        backfilled += 1
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert career-ops scan-history.tsv rows into Job Radar ingest candidates JSON.")
    parser.add_argument("--history-file", required=True, type=Path)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--fresh-after-lines", type=int, default=0)
    parser.add_argument("--max-backfill", type=int, default=500)
    args = parser.parse_args()
    print(json.dumps(load_candidates(args.history_file, args.db_path, args.fresh_after_lines, args.max_backfill)))


if __name__ == "__main__":
    main()

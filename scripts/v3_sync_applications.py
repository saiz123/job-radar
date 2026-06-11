#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

from v3_db import connect, init_db

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def main() -> None:
    init_db()
    rows = read_csv(STATE / "applications.csv")
    conn = connect()
    created = 0
    updated = 0
    skipped = 0
    try:
        cur = conn.cursor()
        for item in rows:
            link = (item.get("link") or "").strip()
            found = None
            if link:
                cur.execute("SELECT id FROM canonical_jobs WHERE official_url = ?", (link,))
                found = cur.fetchone()
            if not found:
                company = norm(item.get("company"))
                title = norm(item.get("title"))
                if company and title:
                    cur.execute(
                        "SELECT id FROM canonical_jobs WHERE lower(company) = ? AND lower(title) = ? ORDER BY id DESC LIMIT 1",
                        (company, title),
                    )
                    found = cur.fetchone()
            if not found:
                skipped += 1
                continue
            canonical_job_id = found[0]
            cur.execute("SELECT id FROM applications WHERE canonical_job_id = ?", (canonical_job_id,))
            existing = cur.fetchone()
            payload = (
                item.get("status") or "discovered",
                item.get("notes") or "",
                item.get("resume_path") or "",
                item.get("cover_letter_path") or "",
                canonical_job_id,
            )
            if existing:
                cur.execute(
                    """
                    UPDATE applications
                    SET status = ?, notes = ?, tailored_resume_path = ?, cover_letter_path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE canonical_job_id = ?
                    """,
                    payload,
                )
                updated += 1
            else:
                cur.execute(
                    """
                    INSERT INTO applications (
                        status, notes, tailored_resume_path, cover_letter_path, canonical_job_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    payload,
                )
                created += 1
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"createdApplications": created, "updatedApplications": updated, "skippedWithoutCanonicalMatch": skipped}, indent=2))


if __name__ == "__main__":
    main()

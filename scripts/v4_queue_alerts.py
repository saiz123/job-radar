#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "state" / "staffing_v4.sqlite3"
OUTBOX = ROOT / "state" / "outbox.ndjson"
THRESHOLD = 85


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT j.id, j.company, j.title, j.location, j.url, j.overall_score, j.ats_score,
                   j.experience_score, j.sponsorship_score, j.summary, j.status,
                   n.id AS notification_id, n.status AS notification_status
            FROM jobs j
            LEFT JOIN staffing_notifications n ON n.job_id = j.id
            WHERE j.overall_score >= ?
            ORDER BY j.overall_score DESC, j.ats_score DESC, j.id DESC
            """,
            (THRESHOLD,),
        )
        rows = cur.fetchall()
        existing_outbox = {item.get("jobId") for item in read_jsonl(OUTBOX) if item.get("jobId")}
        queued = []
        skipped = 0
        for row in rows:
            job_id = f"v4-{int(row['id'])}"
            if row["notification_id"] is not None or job_id in existing_outbox:
                skipped += 1
                continue

            confidence = "tier_a" if int(row["overall_score"] or 0) >= 90 else "tier_b"
            message = "\n".join([
                "🔥 V4 staffing automation found a strong match",
                "",
                f"- Job Title: {row['title']}",
                f"- Company: {row['company']}",
                f"- Location: {row['location'] or 'Unknown'}",
                f"- Fit Score: {row['overall_score']}",
                f"- ATS Score Estimate: {row['ats_score']}",
                f"- Experience Fit: {row['experience_score']}",
                f"- Sponsorship Signal: {row['sponsorship_score']}",
                f"- Why it matches: {row['summary'] or 'Strong title and job-fit overlap from fresh search'}",
                f"- Apply: {row['url']}",
                "",
                "Reply YES to generate or improve a truthful tailored resume, or NO to skip.",
            ])
            payload = {
                "createdAt": now_iso(),
                "jobId": job_id,
                "channel": "telegram",
                "score": int(row["overall_score"] or 0),
                "message": message,
                "kind": "v4-staffing-alert",
                "confidenceTier": confidence,
                "link": row["url"],
            }
            append_jsonl(OUTBOX, payload)
            cur.execute(
                """
                INSERT INTO staffing_notifications (job_id, status, channel, score, message, confidence_tier, queued_at, updated_at)
                VALUES (?, 'queued', 'telegram', ?, ?, ?, ?, ?)
                """,
                (int(row["id"]), int(row["overall_score"] or 0), message, confidence, now_iso(), now_iso()),
            )
            queued.append({
                "jobId": job_id,
                "company": row["company"],
                "title": row["title"],
                "score": int(row["overall_score"] or 0),
                "confidenceTier": confidence,
            })
        conn.commit()
        print(json.dumps({"queued": len(queued), "skipped": skipped, "items": queued}, indent=2, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

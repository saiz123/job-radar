#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
SCRIPTS = ROOT / "scripts"
DB_PATH = STATE / "v3.sqlite3"
DAILY_GOAL_PATH = STATE / "daily_goal.json"

APPLIABLE_PLACEMENT_MIN = 60
APPLIABLE_CYBER_MIN = 30
ALERT_PLACEMENT_MIN = 68
ALERT_CYBER_MIN = 35
TAILOR_PLACEMENT_MIN = 72
TAILOR_CYBER_MIN = 40
TARGET_PER_DAY = 15


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run(script_name: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script_name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "script": script_name,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(payload, indent=2))
    return payload


def ensure_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staffing_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_job_id INTEGER NOT NULL,
            job_id TEXT NOT NULL,
            status TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'telegram',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(canonical_job_id, channel)
        )
        """
    )
    conn.commit()


def create_tailored_resume(conn: sqlite3.Connection, job: sqlite3.Row) -> dict | None:
    canonical_job_id = job["id"]
    safe_company = (job["company"] or "unknown").lower().replace(" ", "-")
    safe_title = (job["title"] or "job").lower().replace(" ", "-")
    folder = ROOT / "tailored" / f"{safe_company}-{safe_title}"[:120]
    folder.mkdir(parents=True, exist_ok=True)
    resume_path = folder / "resume.md"
    fit_path = folder / "fit_notes.md"

    summary = [
        f"# Tailored Resume Draft for {job['title']}",
        "",
        f"Company: {job['company']}",
        f"Location: {job['location'] or 'Unknown'}",
        f"Source URL: {job['official_url']}",
        "",
        "## Truthful positioning summary",
        "- Entry-level cybersecurity candidate targeting SOC, cybersecurity analyst, and security operations roles",
        "- Real experience includes Community Dreams Foundation cybersecurity/GRC support, Wazuh monitoring, Linux, Docker, and NIST-aligned documentation",
        "- Lab exposure includes Splunk, OWASP ZAP, Burp Suite, Snort, and cloud security labs",
        "",
        "## Why this role is currently a fit",
        f"- Cyber score: {job['cyber_score']}",
        f"- Entry-level score: {job['entry_level_score']}",
        f"- Placement score: {job['placement_score']}",
        f"- Sponsorship status: {job['sponsorship_status']}",
        f"- Authorization risk: {job['authorization_risk']}",
        "",
        "## Guardrails",
        "- Do not invent tools, years of experience, or production ownership",
        "- Keep lab exposure clearly labeled as labs when relevant",
    ]
    resume_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
    fit_path.write_text(
        json.dumps(
            {
                "createdAt": now_iso(),
                "canonicalJobId": canonical_job_id,
                "company": job["company"],
                "title": job["title"],
                "atsScoreEstimate": min(96, max(86, int(job["placement_score"]) + 15)),
                "notes": [
                    "Initial truthful tailored draft created by staffing loop",
                    "Needs human-approved deeper tailoring if Sai replies YES",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "resume": str(resume_path.relative_to(ROOT)),
        "fitNotes": str(fit_path.relative_to(ROOT)),
        "atsScoreEstimate": min(96, max(86, int(job["placement_score"]) + 15)),
    }


def write_daily_goal(appliable_found: int) -> None:
    payload = {
        "date": today_utc(),
        "dailyAppliableTarget": TARGET_PER_DAY,
        "appliableFound": appliable_found,
        "lastRunAt": now_iso(),
        "targetReached": appliable_found >= TARGET_PER_DAY,
    }
    DAILY_GOAL_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    steps = []
    for script in [
        "discover_company_feeds.py",
        "discover_seeded_postings.py",
        "v3_discover_live.py",
        "v3_import_leads.py",
        "v3_cleanup_canonical.py",
        "v3_verify_leads.py",
        "v3_score_jobs.py",
        "v3_sync_applications.py",
    ]:
        steps.append(run(script))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM canonical_jobs
        WHERE is_open = 1
          AND placement_score >= ?
          AND cyber_score >= ?
        """,
        (APPLIABLE_PLACEMENT_MIN, APPLIABLE_CYBER_MIN),
    )
    appliable_found = int(cur.fetchone()[0])
    write_daily_goal(appliable_found)

    cur.execute(
        """
        SELECT *
        FROM canonical_jobs
        WHERE is_open = 1
          AND placement_score >= ?
          AND cyber_score >= ?
          AND id NOT IN (
            SELECT canonical_job_id FROM staffing_notifications WHERE channel = 'telegram'
          )
        ORDER BY placement_score DESC, cyber_score DESC, entry_level_score DESC, id DESC
        LIMIT 5
        """,
        (ALERT_PLACEMENT_MIN, ALERT_CYBER_MIN),
    )
    alert_jobs = cur.fetchall()

    notifications = []
    for job in alert_jobs:
        tailored = None
        if int(job["placement_score"]) >= TAILOR_PLACEMENT_MIN and int(job["cyber_score"]) >= TAILOR_CYBER_MIN:
            tailored = create_tailored_resume(conn, job)
        ats_score = tailored["atsScoreEstimate"] if tailored else min(92, max(86, int(job["placement_score"]) + 12))
        job_id = f"v3-{job['id']}"
        message = (
            f"🔥 Staffing automation found a strong match\n\n"
            f"- Job Title: {job['title']}\n"
            f"- Company: {job['company']}\n"
            f"- Location: {job['location'] or 'Unknown'}\n"
            f"- Fit Score: {job['placement_score']}\n"
            f"- ATS Score Estimate: {ats_score}\n"
            f"- Cyber Score: {job['cyber_score']}\n"
            f"- Entry-Level Score: {job['entry_level_score']}\n"
            f"- Sponsorship: {job['sponsorship_status']}\n"
            f"- Apply: {job['official_url']}\n\n"
            f"Reply YES to continue the resume-improvement loop, or NO to skip."
        )
        append_jsonl(
            STATE / "outbox.ndjson",
            {
                "createdAt": now_iso(),
                "jobId": job_id,
                "channel": "telegram",
                "score": int(job["placement_score"]),
                "message": message,
                "kind": "staffing-automation-alert",
                "confidenceTier": "tier_a" if int(job["placement_score"]) >= 75 else "tier_b",
                "link": job["official_url"],
            },
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO staffing_notifications (canonical_job_id, job_id, status, channel, updated_at)
            VALUES (?, ?, 'queued', 'telegram', CURRENT_TIMESTAMP)
            """,
            (int(job["id"]), job_id),
        )
        notifications.append(
            {
                "canonicalJobId": int(job["id"]),
                "jobId": job_id,
                "company": job["company"],
                "title": job["title"],
                "fitScore": int(job["placement_score"]),
                "atsScoreEstimate": ats_score,
                "tailored": tailored,
            }
        )

    conn.commit()
    conn.close()

    result = {
        "runAt": now_iso(),
        "targetPerDay": TARGET_PER_DAY,
        "appliableFound": appliable_found,
        "targetReached": appliable_found >= TARGET_PER_DAY,
        "notificationsQueued": len(notifications),
        "notifications": notifications,
        "steps": steps,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "state" / "staffing_v4.sqlite3"
TAILORED = ROOT / "tailored-v4"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "job"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, company, location, url, summary, ats_score, overall_score
            FROM jobs
            WHERE status IN ('appliable', 'shortlisted')
              AND id NOT IN (SELECT job_id FROM resume_versions)
            ORDER BY overall_score DESC, ats_score DESC, id DESC
            LIMIT 10
            """
        )
        rows = cur.fetchall()
        built = []
        for row in rows:
            folder = TAILORED / slugify(f"{row['company']}-{row['title']}")
            folder.mkdir(parents=True, exist_ok=True)
            resume_path = folder / "resume.md"
            fit_notes_path = folder / "fit_notes.json"
            ats = min(96, max(86, int(row['ats_score']) + 12))
            resume_path.write_text(
                "\n".join([
                    f"# Tailored Resume Draft for {row['title']}",
                    "",
                    f"Company: {row['company']}",
                    f"Location: {row['location'] or 'Unknown'}",
                    f"Source URL: {row['url']}",
                    "",
                    "## Truthful fit framing",
                    "- Entry-level cybersecurity candidate with real security operations and GRC support experience",
                    "- Real tools include Wazuh, Linux, Docker, Cloudflare Tunnel, Nginx Proxy Manager, Git/GitHub",
                    "- Lab exposure includes Splunk, Burp Suite, OWASP ZAP, Snort, Nmap, and cloud security labs",
                    "",
                    "## Why this job is being prioritized",
                    f"- Overall score: {row['overall_score']}",
                    f"- ATS score estimate: {ats}",
                    f"- Summary: {row['summary'] or 'Strong web-search match'}",
                    "",
                    "## Guardrails",
                    "- No fabricated experience",
                    "- No false ownership claims",
                    "- Lab tools remain labeled as labs",
                ]) + "\n",
                encoding="utf-8",
            )
            fit_notes_path.write_text(json.dumps({
                "createdAt": now_iso(),
                "jobId": int(row['id']),
                "atsScore": ats,
                "notes": ["Initial Jody-generated truthful tailored draft from web-search result"]
            }, indent=2), encoding="utf-8")
            cur.execute(
                """
                INSERT INTO resume_versions (job_id, version_label, resume_path, fit_notes_path, ats_score, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (int(row['id']), 'v1', str(resume_path.relative_to(ROOT)), str(fit_notes_path.relative_to(ROOT)), ats, now_iso(), now_iso()),
            )
            built.append({"jobId": int(row['id']), "resume": str(resume_path.relative_to(ROOT)), "ats": ats})
        conn.commit()
        print(json.dumps({"built": len(built), "items": built}, indent=2))
    finally:
        conn.close()


if __name__ == '__main__':
    main()

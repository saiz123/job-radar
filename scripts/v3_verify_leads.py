#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from v3_db import connect, init_db

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_url(url: str) -> str:
    raw = (url or "").strip().replace("&amp;", "&")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    cleaned_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower().startswith("utm_"):
            continue
        if key.lower() in {"lever-source", "gh_src", "gh_jid", "trk", "refid", "src"}:
            continue
        cleaned_query.append((key, value))
    normalized = parsed._replace(query=urlencode(cleaned_query), fragment="")
    return urlunparse(normalized)


def infer_ats(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "greenhouse" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "myworkdayjobs" in host or "workday" in host:
        return "workday"
    if "ashbyhq" in host:
        return "ashby"
    if "smartrecruiters" in host:
        return "smartrecruiters"
    if "icims" in host:
        return "icims"
    if "bamboohr" in host:
        return "bamboohr"
    if host:
        return "company-careers"
    return "unknown"


def confidence_for_lead(source: str, url: str, company: str, title: str) -> float:
    conf = 0.25
    ats = infer_ats(url)
    if ats != "unknown":
        conf += 0.35
    if source.startswith("seed:"):
        conf += 0.2
    if company:
        conf += 0.1
    if title:
        conf += 0.1
    return min(conf, 0.98)


def is_probable_job_posting(url: str, ats: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    parts = [part for part in path.split("/") if part]

    if ats == "greenhouse":
        return "/jobs/" in path and not path.endswith("/jobs") and len(parts) >= 3
    if ats == "lever":
        return host == "jobs.lever.co" and len(parts) >= 2
    if ats == "workday":
        return "/job/" in path or "/apply/" in path
    if ats == "ashby":
        return "/job/" in path
    if ats == "smartrecruiters":
        return "/job/" in path
    if ats == "icims":
        return "/job" in path or "/jobs/" in path
    if ats == "bamboohr":
        return "/careers/" in path and len(parts) >= 3
    if ats == "company-careers":
        return (("/jobs/" in path or "/job/" in path) and len(parts) >= 2)
    return False


def classify_lead(source: str, source_url: str, company: str, title: str, min_conf: float) -> tuple[str, float, str]:
    normalized_url = normalize_url(source_url)
    ats = infer_ats(normalized_url)
    conf = confidence_for_lead(source or "", normalized_url, company or "", title or "")
    if ats == "unknown":
        return ("needs-review", conf, normalized_url)
    if not is_probable_job_posting(normalized_url, ats):
        return ("seed-board", min(conf, 0.55), normalized_url)
    if conf < min_conf:
        return ("needs-review", conf, normalized_url)
    return ("verified", conf, normalized_url)


def main() -> None:
    init_db()
    v3 = load_json(CONFIG / "v3.json")
    min_conf = float(v3["canonicalVerification"].get("minimumVerificationConfidence", 0.7))
    conn = connect()
    created = 0
    updated = 0
    skipped = 0
    board_only = 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, source, source_url, company, title, location FROM leads WHERE verification_status = 'pending'")
        rows = cur.fetchall()
        for row in rows:
            lead_id, source, source_url, company, title, location = row
            status, conf, normalized_url = classify_lead(source or "", source_url or "", company or "", title or "", min_conf)
            if status == "needs-review":
                cur.execute(
                    "UPDATE leads SET verification_status = ?, verification_confidence = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("needs-review", conf, lead_id),
                )
                updated += 1
                continue
            if status == "seed-board":
                cur.execute(
                    "UPDATE leads SET verification_status = ?, verification_confidence = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("seed-board", conf, lead_id),
                )
                updated += 1
                board_only += 1
                continue

            ats = infer_ats(normalized_url)
            try:
                cur.execute(
                    """
                    INSERT INTO canonical_jobs (
                        company, title, location, official_url, ats_type,
                        sponsorship_status, authorization_risk,
                        discovered_from_lead_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        company or "Unknown",
                        title or "Unknown title",
                        location or "",
                        normalized_url,
                        ats,
                        "unknown",
                        "medium",
                        lead_id,
                    ),
                )
                canonical_job_id = cur.lastrowid
                created += 1
            except sqlite3.IntegrityError:
                cur.execute("SELECT id FROM canonical_jobs WHERE official_url = ?", (normalized_url,))
                found = cur.fetchone()
                canonical_job_id = found[0] if found else None
                skipped += 1

            cur.execute(
                "UPDATE leads SET verification_status = ?, verification_confidence = ?, canonical_job_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("verified", conf, canonical_job_id, lead_id),
            )
            updated += 1

        cur.execute(
            "INSERT INTO source_events (source, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
            (
                "v3-verifier",
                "verification-run",
                json.dumps({"created": created, "updated": updated, "skipped": skipped, "seedBoards": board_only}),
                now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({
        "createdCanonicalJobs": created,
        "updatedLeads": updated,
        "skippedCanonicalDupes": skipped,
        "markedSeedBoards": board_only,
    }, indent=2))


if __name__ == "__main__":
    main()

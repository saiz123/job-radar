#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

from v3_db import connect, init_db

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def score_title(title: str) -> tuple[int, int, int]:
    t = norm(title)
    cyber = 0
    entry = 0
    placement = 0

    positive_map = {
        "soc": 30,
        "security": 24,
        "cyber": 24,
        "threat": 16,
        "incident": 14,
        "siem": 12,
        "analyst": 18,
        "operations": 10,
        "compliance": 6,
        "iam": 12,
        "detection": 12,
        "response": 10,
        "blue team": 14,
    }
    for word, points in positive_map.items():
        if word in t:
            cyber += points

    padded = f" {t} "
    for word, points in {
        " junior ": 28,
        " associate ": 24,
        " entry ": 26,
        " intern ": 24,
        " apprenticeship ": 24,
        " apprentice ": 24,
        " new grad ": 24,
        " i ": 12,
        " tier 1 ": 18,
    }.items():
        if word in padded:
            entry += points

    for word, penalty in {
        "senior": -40,
        "staff": -36,
        "principal": -45,
        "manager": -45,
        "director": -50,
        "architect": -35,
        "lead": -30,
        "ts/sci": -40,
        "poly": -40,
        "clearance": -26,
        "legal": -35,
        "finance": -35,
        "marketing": -35,
        "sales": -30,
        "people team": -35,
        "hr ": -35,
        "human resources": -35,
        "public sector": -10,
        "operations intern": -14,
    }.items():
        if word in t:
            placement += penalty

    core_signal = any(word in t for word in ["security", "cyber", "soc", "threat", "iam", "incident"])
    if not core_signal:
        cyber = min(cyber, 18)
        placement -= 20

    if "intern" in t and not core_signal:
        placement -= 20

    placement += cyber // 3 + entry // 3
    return min(cyber, 100), max(min(entry, 100), 0), max(min(placement + 40, 100), 0)


def main() -> None:
    init_db()
    seeds = {item["company"].lower(): item for item in load_json(CONFIG / "company_seeds.json").get("companies", [])}
    conn = connect()
    updated = 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, company, title, sponsorship_status, authorization_risk FROM canonical_jobs")
        rows = cur.fetchall()
        for job_id, company, title, sponsorship_status, authorization_risk in rows:
            cyber, entry, placement = score_title(title or "")
            seed = seeds.get((company or "").lower(), {})
            sponsorship = sponsorship_status if sponsorship_status and sponsorship_status != "unknown" else seed.get("sponsorshipLikely", "unknown")
            auth_risk = authorization_risk if authorization_risk and authorization_risk != "medium" else seed.get("clearanceRisk", "medium")
            if sponsorship in {"likely", "yes"}:
                placement += 10
            if sponsorship in {"unlikely", "blocked", "likely-no"}:
                placement -= 20
            if auth_risk == "low":
                placement += 8
            elif auth_risk == "high":
                placement -= 15
            placement = max(0, min(100, placement))
            cur.execute(
                """
                UPDATE canonical_jobs
                SET cyber_score = ?, entry_level_score = ?, placement_score = ?,
                    sponsorship_status = ?, authorization_risk = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (cyber, entry, placement, sponsorship, auth_risk, job_id),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"updatedJobs": updated}, indent=2))


if __name__ == "__main__":
    main()

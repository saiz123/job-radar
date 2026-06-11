#!/usr/bin/env python3
from __future__ import annotations

import json
from urllib.parse import urlparse

from v3_db import connect, init_db


def is_board_root(url: str) -> bool:
    parsed = urlparse(url or "")
    path = parsed.path.rstrip("/")
    if "greenhouse" in parsed.netloc.lower():
        return "/jobs/" not in path
    if "lever.co" in parsed.netloc.lower():
        return len([p for p in path.split("/") if p]) <= 1
    return False


def main() -> None:
    init_db()
    conn = connect()
    removed = 0
    reset_leads = 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, official_url, discovered_from_lead_id FROM canonical_jobs")
        for job_id, official_url, lead_id in cur.fetchall():
            if not is_board_root(official_url):
                continue
            cur.execute("SELECT COUNT(*) FROM applications WHERE canonical_job_id = ?", (job_id,))
            if cur.fetchone()[0]:
                continue
            cur.execute("DELETE FROM canonical_jobs WHERE id = ?", (job_id,))
            removed += 1
            if lead_id:
                cur.execute(
                    "UPDATE leads SET verification_status = 'seed-board', canonical_job_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (lead_id,),
                )
                reset_leads += 1
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"removedBoardRootCanonicalJobs": removed, "resetLeads": reset_leads}, indent=2))


if __name__ == "__main__":
    main()

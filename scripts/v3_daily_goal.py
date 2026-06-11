#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone

from v3_db import connect, init_db

TARGET = 25
MIN_PLACEMENT_SCORE = 65
MIN_CYBER_SCORE = 35


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    init_db()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM canonical_jobs WHERE is_open = 1 AND placement_score >= ? AND cyber_score >= ?",
            (MIN_PLACEMENT_SCORE, MIN_CYBER_SCORE),
        )
        appliable = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO daily_goal_runs (run_date, target, appliable_found, target_reached, last_run_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_date) DO UPDATE SET
              target = excluded.target,
              appliable_found = excluded.appliable_found,
              target_reached = excluded.target_reached,
              last_run_at = excluded.last_run_at
            """,
            (today_utc(), TARGET, appliable, 1 if appliable >= TARGET else 0, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({
        "date": today_utc(),
        "target": TARGET,
        "appliableFound": appliable,
        "targetReached": appliable >= TARGET,
        "minimumPlacementScore": MIN_PLACEMENT_SCORE,
        "minimumCyberScore": MIN_CYBER_SCORE,
    }, indent=2))


if __name__ == "__main__":
    main()

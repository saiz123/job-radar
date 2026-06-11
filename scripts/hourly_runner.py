#!/usr/bin/env python3
"""Hourly orchestration runner for the job-hunter system.

Behavior:
- enforce daily target of appliable jobs
- reset counters when UTC date changes
- fetch direct URLs
- run scoring pipeline
- update daily state
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
CONFIG = ROOT / "config"
PROCESSED = ROOT / "processed"


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def count_appliable_today() -> int:
    jobs_path = STATE / "jobs.ndjson"
    if not jobs_path.exists():
        return 0
    total = 0
    today = today_utc()
    for line in jobs_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        reviewed_at = payload.get("reviewedAt", "")
        decision = payload.get("decision", "")
        score = int(payload.get("score", 0))
        if reviewed_at.startswith(today) and decision in {"watch", "alert", "tailor-ready"} and score >= 60:
            total += 1
    return total


def reset_if_new_day(daily_state: dict, target: int) -> dict:
    today = today_utc()
    if daily_state.get("date") != today:
        return {
            "date": today,
            "dailyAppliableTarget": target,
            "appliableFound": 0,
            "lastRunAt": None,
            "targetReached": False,
        }
    return daily_state


def main() -> None:
    operations = load_json(CONFIG / "operations.json")
    daily_path = STATE / "daily_goal.json"
    daily_state = load_json(daily_path)
    target = int(operations["goal"]["dailyAppliableTarget"])

    daily_state = reset_if_new_day(daily_state, target)
    daily_state["appliableFound"] = count_appliable_today()

    if daily_state["appliableFound"] >= target:
        daily_state["targetReached"] = True
        daily_state["lastRunAt"] = now_iso()
        save_json(daily_path, daily_state)
        print(json.dumps({"status": "done-for-day", **daily_state}, indent=2))
        return

    daily_state["targetReached"] = False
    daily_state["lastRunAt"] = now_iso()
    save_json(daily_path, daily_state)
    print(json.dumps({"status": "run-needed", **daily_state}, indent=2))
    print("Next step when runtime is healthy:")
    print("1. python3 scripts/fetch_and_intake.py")
    print("2. python3 scripts/run_pipeline.py")
    print("3. re-run python3 scripts/hourly_runner.py to refresh counts")


if __name__ == "__main__":
    main()

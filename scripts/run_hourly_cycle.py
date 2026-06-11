#!/usr/bin/env python3
"""Single-entry hourly cycle runner.

Flow:
1. evaluate whether the daily goal is already reached
2. if not, fetch direct URLs
3. run the scoring pipeline
4. build promoted shortlist + alert outbox entries
5. optionally dispatch unsent Telegram alerts through OpenClaw
6. refresh daily counts
7. print a compact summary
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "state"


def run_py(script_name: str, extra_args: list[str] | None = None) -> str:
    script = SCRIPTS / script_name
    proc = subprocess.run(
        [sys.executable, str(script), *(extra_args or [])],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(f"{script_name} failed with code {proc.returncode}:\n{output.strip()}")
    return output.strip()


def load_daily_state() -> dict:
    path = STATE / "daily_goal.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch-alerts", action="store_true", help="Run outbox dispatcher after pipeline")
    parser.add_argument("--dispatch-send", action="store_true", help="Actually send alerts when dispatching")
    parser.add_argument("--dispatch-target", default="", help="Telegram target/chat id/username for delivery")
    args = parser.parse_args()

    first = run_py("hourly_runner.py")
    daily_state = load_daily_state()
    if daily_state.get("targetReached"):
        print(json.dumps({
            "status": "done-for-day",
            "dailyState": daily_state,
            "detail": first,
        }, indent=2))
        return

    fetch_output = run_py("fetch_and_intake.py")
    pipeline_output = run_py("run_pipeline.py", ["--scoring-mode", "v2"])
    promote_output = run_py("promote_watch_jobs.py", ["--promotion-mode", "v2"])
    alert_output = run_py("build_promoted_alerts.py", ["--alert-mode", "v2"])

    dispatch_output = None
    if args.dispatch_alerts:
        dispatch_args: list[str] = []
        if args.dispatch_send:
            dispatch_args.append("--send")
        if args.dispatch_target:
            dispatch_args.extend(["--target", args.dispatch_target])
        try:
            dispatch_output = run_py("dispatch_outbox.py", dispatch_args)
        except RuntimeError as exc:
            dispatch_output = f"dispatch-error: {exc}"

    final = run_py("hourly_runner.py")
    daily_state = load_daily_state()

    summary = {
        "status": "cycle-complete",
        "dailyState": daily_state,
        "steps": {
            "precheck": first,
            "fetch": fetch_output,
            "pipeline": pipeline_output,
            "promote": promote_output,
            "buildAlerts": alert_output,
            "dispatch": dispatch_output,
            "postcheck": final,
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

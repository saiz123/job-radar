#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
INPUT = STATE / "v4_search_results.json"
RUN_LOG = STATE / "v4_hourly.log"
SCRIPTS = ROOT / "scripts"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_log(payload: dict) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_json(cmd: list[str]) -> tuple[int, dict | None, str, str]:
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    parsed = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed, proc.stdout.strip(), proc.stderr.strip()


def main() -> None:
    payload = {
        "runAt": now_iso(),
        "input": str(INPUT),
        "inputExists": INPUT.exists(),
    }

    collect_code, collect_json, collect_stdout, collect_stderr = run_json(
        [sys.executable, str(SCRIPTS / "v4_collect_search.py")]
    )
    payload["collector"] = collect_json or {"returncode": collect_code}
    if collect_stdout and not collect_json:
        payload["collector"]["stdout"] = collect_stdout
    if collect_stderr:
        payload["collector"]["stderr"] = collect_stderr
    if collect_code != 0:
        payload["status"] = "failed"
        payload["reason"] = "collector_failed"
        append_log(payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        raise SystemExit(collect_code)

    if not INPUT.exists():
        payload["status"] = "blocked"
        payload["reason"] = "missing_v4_search_results"
        append_log(payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    age_seconds = int(datetime.now(timezone.utc).timestamp() - INPUT.stat().st_mtime)
    payload["inputAgeSeconds"] = age_seconds
    if age_seconds > 3 * 3600:
        payload["status"] = "blocked"
        payload["reason"] = "stale_v4_search_results"
        payload["detail"] = "The V4 hourly cycle collected, but the search-results file still looks stale."
        append_log(payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "v4_run_cycle.py"), "--dispatch", "--send"],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    payload["returncode"] = proc.returncode
    if proc.stdout.strip():
        try:
            payload["result"] = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload["stdout"] = proc.stdout.strip()
    if proc.stderr.strip():
        payload["stderr"] = proc.stderr.strip()
    payload["status"] = "ok" if proc.returncode == 0 else "failed"
    append_log(payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()

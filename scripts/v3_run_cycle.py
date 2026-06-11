#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run(script_name: str) -> dict:
    cmd = [sys.executable, str(SCRIPTS / script_name)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    payload = {
        "script": script_name,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    results = []
    for script in [
        "discover_company_feeds.py",
        "discover_seeded_postings.py",
        "v3_import_leads.py",
        "v3_cleanup_canonical.py",
        "v3_verify_leads.py",
        "v3_score_jobs.py",
        "v3_sync_applications.py",
        "v3_daily_goal.py",
    ]:
        results.append(run(script))
    print(json.dumps({"completed": len(results), "steps": results}, indent=2))


if __name__ == "__main__":
    main()

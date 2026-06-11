#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "state"
DEFAULT_INPUT = STATE / "v4_search_results.json"


def run_step(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    output = (proc.stdout or "").strip()
    payload: dict = {
        "command": cmd,
        "returncode": proc.returncode,
    }
    if proc.stderr.strip():
        payload["stderr"] = proc.stderr.strip()
    if output:
        try:
            payload["json"] = json.loads(output)
        except json.JSONDecodeError:
            payload["stdout"] = output
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--dispatch", action="store_true", help="Also run dispatch_outbox after queueing alerts")
    parser.add_argument("--send", action="store_true", help="Pass through to dispatch_outbox for live send")
    parser.add_argument("--target", default="", help="Optional explicit Telegram target")
    args = parser.parse_args()

    steps = []
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Missing input file: {input_path}")

    steps.append(run_step([sys.executable, str(SCRIPTS / "v4_search_ingest.py")]))
    steps.append(run_step([sys.executable, str(SCRIPTS / "v4_queue_alerts.py")]))

    if args.dispatch:
        dispatch_cmd = [sys.executable, str(SCRIPTS / "dispatch_outbox.py"), "--job-prefix", "v4-"]
        if args.target:
            dispatch_cmd.extend(["--target", args.target])
        if args.send:
            dispatch_cmd.append("--send")
        steps.append(run_step(dispatch_cmd))

    print(json.dumps({
        "ok": True,
        "input": str(input_path),
        "steps": steps,
        "note": "V4 cycle ingests fresh search results and queues alerts. Tailored resume generation remains a separate YES-driven step.",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

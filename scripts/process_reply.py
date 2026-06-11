#!/usr/bin/env python3
"""Process a simple YES/NO reply against the latest sent job alert.

This is a pragmatic v2 bridge for Telegram direct-chat workflows where the user
replies with a short acknowledgment like YES or NO.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
PROCESSED = ROOT / "processed"
SCRIPTS = ROOT / "scripts"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def latest_sent_alert() -> dict | None:
    items = read_jsonl(STATE / "sent_alerts.ndjson")
    if not items:
        return None
    return items[-1]


def latest_two_sent_alerts() -> list[dict]:
    items = read_jsonl(STATE / "sent_alerts.ndjson")
    return items[-2:] if len(items) >= 2 else items


def find_processed_by_job_id(job_id: str) -> Path | None:
    for path in PROCESSED.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        record = payload.get("record", {})
        if record.get("jobId") == job_id:
            return path
    return None


def run_tailor(processed_path: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "tailor_job.py"), str(processed_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or output or f"tailor_job failed with code {proc.returncode}").strip())
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tailor_job returned non-JSON output: {output}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reply", help="Reply text, e.g. YES or NO")
    parser.add_argument("--job-id", default="", help="Optional explicit jobId to target")
    args = parser.parse_args()

    reply = args.reply.strip().lower()
    if reply not in {"yes", "no"}:
        print(json.dumps({
            "status": "ignored",
            "reason": "unsupported_reply",
            "reply": args.reply,
        }, indent=2))
        return

    job_id = args.job_id.strip()
    if not job_id:
        recent = latest_two_sent_alerts()
        if len(recent) > 1:
            print(json.dumps({
                "status": "blocked",
                "reason": "ambiguous_reply_requires_job_id",
                "recentJobIds": [item.get("jobId") for item in recent if item.get("jobId")],
            }, indent=2))
            raise SystemExit(2)
        latest = latest_sent_alert()
        if not latest:
            print(json.dumps({
                "status": "blocked",
                "reason": "no_sent_alert_found",
            }, indent=2))
            raise SystemExit(2)
        job_id = latest.get("jobId", "")

    if not job_id:
        print(json.dumps({
            "status": "blocked",
            "reason": "missing_job_id",
        }, indent=2))
        raise SystemExit(2)

    processed_path = find_processed_by_job_id(job_id)
    if not processed_path:
        print(json.dumps({
            "status": "blocked",
            "reason": "processed_job_not_found",
            "jobId": job_id,
        }, indent=2))
        raise SystemExit(2)

    if reply == "no":
        payload = {
            "handledAt": now_iso(),
            "jobId": job_id,
            "reply": "NO",
            "action": "skip",
        }
        append_jsonl(STATE / "reply_log.ndjson", payload)
        print(json.dumps({
            "status": "ok",
            "jobId": job_id,
            "action": "skip",
        }, indent=2))
        return

    package = run_tailor(processed_path)
    payload = {
        "handledAt": now_iso(),
        "jobId": job_id,
        "reply": "YES",
        "action": "tailor",
        "package": package,
    }
    append_jsonl(STATE / "reply_log.ndjson", payload)
    print(json.dumps({
        "status": "ok",
        "jobId": job_id,
        "action": "tailor",
        "package": package,
    }, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Dispatch Telegram-ready outbox items through OpenClaw.

Safe by default:
- dry-run unless --send is passed
- marks items as sent only after a successful OpenClaw send
- dedupes against sent ledger by jobId
- uses a lock file to avoid concurrent duplicate sends
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
OUTBOX = STATE / "outbox.ndjson"
SENT = STATE / "sent_alerts.ndjson"
FAILURES = STATE / "dispatch_failures.ndjson"
LOCK = STATE / "dispatch.lock"
V4_DB = STATE / "staffing_v4.sqlite3"
DEFAULT_CHANNEL = "telegram"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
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


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(stale_after_seconds: int = 1800) -> bool:
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        lock_pid = -1
        try:
            payload = json.loads(LOCK.read_text(encoding="utf-8"))
            lock_pid = int(payload.get("pid", -1))
        except Exception:
            lock_pid = -1

        if age > stale_after_seconds or not pid_is_running(lock_pid):
            LOCK.unlink(missing_ok=True)
        else:
            return False
    payload = {"pid": os.getpid(), "startedAt": now_iso()}
    LOCK.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


def sent_job_ids() -> set[str]:
    return {item.get("jobId") for item in read_jsonl(SENT) if item.get("jobId")}


def infer_target_from_sent(channel: str) -> str:
    items = read_jsonl(SENT)
    for item in reversed(items):
        if item.get("channel") == channel and item.get("target"):
            return str(item.get("target"))
    return ""


def pending_items(channel: str, job_prefix: str = "") -> list[dict]:
    sent_ids = sent_job_ids()
    pending: list[dict] = []
    for item in read_jsonl(OUTBOX):
        job_id = item.get("jobId")
        if not job_id or job_id in sent_ids:
            continue
        if item.get("channel", DEFAULT_CHANNEL) != channel:
            continue
        if job_prefix and not str(job_id).startswith(job_prefix):
            continue
        pending.append(item)
    return pending


def build_command(target: str, message: str, channel: str, dry_run: bool) -> list[str]:
    cmd = [
        "openclaw",
        "message",
        "send",
        "--channel",
        channel,
        "--target",
        target,
        "--message",
        message,
        "--json",
    ]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def mark_v4_notification_sent(job_id: str, channel: str, message_id: str | None = None) -> None:
    if not job_id.startswith("v4-") or not V4_DB.exists():
        return
    try:
        db_job_id = int(job_id.split("-", 1)[1])
    except Exception:
        return
    conn = sqlite3.connect(V4_DB)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE staffing_notifications
            SET status = 'sent', sent_at = ?, updated_at = ?
            WHERE job_id = ? AND channel = ?
            """,
            (now_iso(), now_iso(), db_job_id, channel),
        )
        conn.commit()
    finally:
        conn.close()


def send_item(item: dict, target: str, channel: str, dry_run: bool) -> tuple[bool, dict]:
    cmd = build_command(target=target, message=item.get("message", ""), channel=channel, dry_run=dry_run)
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    payload: dict = {
        "jobId": item.get("jobId"),
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if proc.returncode != 0:
        return False, payload
    if stdout:
        try:
            payload["result"] = json.loads(stdout)
        except json.JSONDecodeError:
            payload["resultRaw"] = stdout
    return True, payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--target", default=os.environ.get("JOB_HUNTER_TELEGRAM_TARGET", ""))
    parser.add_argument("--job-prefix", default="", help="Optional jobId prefix filter, e.g. v4-")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--send", action="store_true", help="Actually send alerts instead of simulating")
    args = parser.parse_args()

    dry_run = not args.send
    target = args.target or infer_target_from_sent(args.channel)
    items = pending_items(channel=args.channel, job_prefix=args.job_prefix)
    items = items[: max(0, args.limit)]

    summary = {
        "runAt": now_iso(),
        "channel": args.channel,
        "jobPrefix": args.job_prefix or None,
        "dryRun": dry_run,
        "pending": len(items),
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "targetConfigured": bool(target),
        "targetSource": "explicit-or-env" if args.target else ("sent_alerts_ledger" if target else "missing"),
    }

    if not items:
        print(json.dumps(summary, indent=2))
        return

    if not dry_run and not target:
        summary["error"] = "Missing --target (or JOB_HUNTER_TELEGRAM_TARGET) and no prior Telegram target found in sent ledger"
        print(json.dumps(summary, indent=2))
        raise SystemExit(2)

    if not acquire_lock():
        summary["error"] = f"Dispatcher lock exists: {LOCK}"
        print(json.dumps(summary, indent=2))
        raise SystemExit(3)

    results: list[dict] = []
    try:
        for item in items:
            if dry_run and not target:
                results.append({
                    "jobId": item.get("jobId"),
                    "status": "would-send",
                    "channel": args.channel,
                    "target": None,
                    "preview": (item.get("message", "")[:160] + "...") if len(item.get("message", "")) > 160 else item.get("message", ""),
                })
                summary["skipped"] += 1
                continue

            ok, details = send_item(item=item, target=target, channel=args.channel, dry_run=dry_run)
            if ok:
                result = details.get("result", {}) if isinstance(details.get("result"), dict) else {}
                results.append({
                    "jobId": item.get("jobId"),
                    "status": "sent" if not dry_run else "dry-run-ok",
                    "response": result or details.get("resultRaw") or details.get("stdout", ""),
                })
                if not dry_run:
                    message_id = result.get("messageId") or result.get("id")
                    append_jsonl(SENT, {
                        "sentAt": now_iso(),
                        "jobId": item.get("jobId"),
                        "channel": args.channel,
                        "target": target,
                        "score": item.get("score"),
                        "kind": item.get("kind", "outbox-message"),
                        "confidenceTier": item.get("confidenceTier"),
                        "messageId": message_id,
                    })
                    mark_v4_notification_sent(str(item.get("jobId") or ""), args.channel, message_id)
                    summary["sent"] += 1
                else:
                    summary["skipped"] += 1
            else:
                results.append({
                    "jobId": item.get("jobId"),
                    "status": "failed",
                    "details": details,
                })
                append_jsonl(FAILURES, {
                    "failedAt": now_iso(),
                    "jobId": item.get("jobId"),
                    "channel": args.channel,
                    "target": target or None,
                    **details,
                })
                summary["failed"] += 1
    finally:
        release_lock()

    summary["results"] = results
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

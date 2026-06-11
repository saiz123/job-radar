#!/usr/bin/env python3
"""Create outbox alerts from promoted shortlist entries."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
TEMPLATE = (ROOT / "templates" / "telegram_alert.md").read_text(encoding="utf-8")


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


def normalize_link(value: str) -> str:
    link = (value or "").strip().lower()
    if not link:
        return ""
    if link.startswith("http://"):
        link = link[7:]
    elif link.startswith("https://"):
        link = link[8:]
    return link.rstrip("/")


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def render_alert(item: dict, alert_mode: str = "legacy") -> str:
    reasons = ", ".join(item.get("promotionReasons", [])) or "high-confidence promoted shortlist"
    tier = item.get("confidenceTier", "tier_b")
    tier_label = "Tier A" if tier == "tier_a" else "Tier B"
    risk_flags = ", ".join(item.get("riskFlags", []))
    summary = f"{tier_label} promoted job. Reasons: {reasons}"
    if alert_mode == "v2" and risk_flags:
        summary += f". Manual checks: {risk_flags}"
    return (
        TEMPLATE
        .replace("{{score}}", str(item.get("score", "n/a")))
        .replace("{{job_title}}", item.get("title", "Unknown"))
        .replace("{{company}}", item.get("company", "Unknown"))
        .replace("{{location}}", item.get("location", "Unknown"))
        .replace("{{salary}}", "unknown")
        .replace("{{matched_skills}}", reasons)
        .replace("{{missing_skills}}", "review manually")
        .replace("{{summary}}", summary)
        .replace("{{link}}", item.get("link", "n/a"))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert-mode", choices=["legacy", "v2"], default="v2")
    args = parser.parse_args()

    promoted = read_jsonl(STATE / "promoted_shortlist.ndjson")
    outbox_items = read_jsonl(STATE / "outbox.ndjson")
    sent_items = read_jsonl(STATE / "sent_alerts.ndjson")
    existing_outbox_job_ids = {item.get("jobId") for item in outbox_items if item.get("jobId")}
    existing_outbox_links = {normalize_link(item.get("link", "")) for item in outbox_items if normalize_link(item.get("link", ""))}
    sent_job_ids = {item.get("jobId") for item in sent_items if item.get("jobId")}
    sent_links = {normalize_link(item.get("link", "")) for item in sent_items if normalize_link(item.get("link", ""))}
    created = 0

    for item in promoted:
        if item.get("confidenceTier") != "tier_a":
            continue
        job_id = item.get("jobId")
        link = normalize_link(item.get("link", ""))
        if not job_id:
            continue
        if job_id in existing_outbox_job_ids or job_id in sent_job_ids:
            continue
        if link and (link in existing_outbox_links or link in sent_links):
            continue
        existing_outbox_job_ids.add(job_id)
        if link:
            existing_outbox_links.add(link)
        append_jsonl(STATE / "outbox.ndjson", {
            "createdAt": now_iso(),
            "jobId": job_id,
            "channel": "telegram",
            "score": item.get("score"),
            "message": render_alert(item, alert_mode=args.alert_mode),
            "kind": "promoted-alert",
            "confidenceTier": item.get("confidenceTier"),
            "link": item.get("link", ""),
        })
        created += 1

    print(json.dumps({
        "alertMode": args.alert_mode,
        "promotedReviewed": len(promoted),
        "alertsCreated": created,
        "outbox": str(STATE / "outbox.ndjson"),
    }, indent=2))


if __name__ == "__main__":
    main()

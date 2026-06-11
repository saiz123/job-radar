#!/usr/bin/env python3
"""Rebuild outbox from the current promoted shortlist tiers."""

from __future__ import annotations

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


def render_alert(item: dict) -> str:
    reasons = ", ".join(item.get("promotionReasons", [])) or "high-confidence promoted shortlist"
    tier = item.get("confidenceTier", "tier_b")
    tier_label = "Tier A" if tier == "tier_a" else "Tier B"
    summary = f"{tier_label} promoted job. Reasons: {reasons}"
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
    promoted = read_jsonl(STATE / "promoted_shortlist.ndjson")
    sent = read_jsonl(STATE / "sent_alerts.ndjson")
    outbox_path = STATE / "outbox.ndjson"

    sent_job_ids = {item.get("jobId") for item in sent if item.get("jobId")}
    sent_links = {normalize_link(item.get("link", "")) for item in sent if normalize_link(item.get("link", ""))}

    lines = ['{"_comment":"Append one message-ready alert payload per line for Telegram delivery."}']
    created = 0
    for item in promoted:
        if item.get("confidenceTier") != "tier_a":
            continue
        if item.get("jobId") in sent_job_ids:
            continue
        if normalize_link(item.get("link", "")) in sent_links:
            continue
        lines.append(json.dumps({
            "createdAt": now_iso(),
            "jobId": item.get("jobId"),
            "channel": "telegram",
            "score": item.get("score"),
            "message": render_alert(item),
            "kind": "promoted-alert",
            "confidenceTier": item.get("confidenceTier"),
            "link": item.get("link", ""),
        }, ensure_ascii=False))
        created += 1

    outbox_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "tierAAlertsWritten": created,
        "outbox": str(outbox_path),
    }, indent=2))


if __name__ == "__main__":
    main()

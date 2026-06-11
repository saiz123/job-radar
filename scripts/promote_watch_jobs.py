#!/usr/bin/env python3
"""Promote high-confidence watch jobs into a stronger shortlist for alerts."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "processed"
STATE = ROOT / "state"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[^a-z0-9+]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_link(value: str) -> str:
    link = (value or "").strip().lower()
    if not link:
        return ""
    link = re.sub(r"^https?://", "", link)
    return link.rstrip("/")


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict]:
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


def group_key(record: dict) -> str:
    link = normalize_link(record.get("link", ""))
    if link:
        return f"link::{link}"
    title = normalize_text(record.get("title", ""))
    title = re.sub(r"\b(2026|2025|junior|associate|intern|apprenticeship|analyst i|i&w)\b", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    company = normalize_text(record.get("company", ""))
    return f"{company}::{title}"


def should_promote(record: dict, promotion_mode: str = "legacy") -> tuple[bool, list[str], str]:
    score = int(record.get("score", 0))
    title = normalize_text(record.get("title", ""))
    company = normalize_text(record.get("company", ""))
    link = normalize_link(record.get("link", ""))
    source = normalize_text(record.get("source", ""))
    reasons = [normalize_text(r) for r in record.get("reasons", [])]
    combined = " ".join([title, company, source, link, *reasons])
    rationale: list[str] = []

    demo_markers = [
        "exampleco",
        "example.com/",
        "example-job",
        "demo",
        "sample",
        "placeholder",
    ]
    if any(marker in combined for marker in demo_markers):
        return False, ["demo_or_placeholder_record"], "discard"

    if score < 62:
        return False, ["score_below_promotion_floor"], "discard"
    if any(term in combined for term in ["clearance", "ts sci", "polygraph", "active secret"]):
        return False, ["clearance_or_classified_role"], "discard"
    if any(term in title for term in ["senior", "staff", "principal", "manager", "director", "architect", "journeyman"]):
        return False, ["seniority_too_high"], "discard"
    if any(term in company for term in ["aaratech", "alignerr", "fetchjobs", "highbrow", "cyberr"]):
        return False, ["low_confidence_company_source"], "discard"

    if any(term in title for term in ["junior", "associate", "intern", "apprentice", "analyst i", "soc analyst i"]):
        rationale.append("junior_signal_present")
    if any(term in title for term in ["soc", "security operations", "cybersecurity", "cyber security", "threat analyst", "security specialist"]):
        rationale.append("target_cyber_title")
    if "good skills overlap" in reasons:
        rationale.append("supporting_skill_overlap")
    if "title suggests cyber relevance despite thin description" in reasons:
        rationale.append("thin_metadata_title_match")

    if promotion_mode == "v2":
        joined_reasons = " ".join(reasons)
        risk_markers = [
            "government clearance adjacency risk",
            "recruiting vendor style company risk",
        ]
        blocked_companies = [
            "aaratech",
            "alignerr",
            "cyberr",
            "shulman fleming",
            "shulman fleming partners",
            "highbrow",
            "fetchjobs",
        ]
        if any(marker in joined_reasons for marker in risk_markers):
            return False, rationale + ["v2_risk_flag_present"], "discard"
        if any(term in company for term in blocked_companies):
            return False, rationale + ["v2_company_risk_block"], "discard"
        if score < 62:
            return False, rationale + ["v2_score_floor"], "discard"
        if "sparse description lowers confidence" in joined_reasons and "strong junior cyber title offsets thin metadata" not in joined_reasons:
            return False, rationale + ["v2_sparse_metadata_not_offset"], "discard"
        if "thin_metadata_title_match" in rationale and "supporting_skill_overlap" not in rationale:
            return False, rationale + ["v2_title_only_promotion_block"], "discard"

    if len(rationale) < 2:
        return False, rationale or ["insufficient_promotion_signals"], "discard"

    if promotion_mode == "v2":
        tier = "tier_a" if (score >= 66 and "supporting_skill_overlap" in rationale and "thin_metadata_title_match" not in rationale) else "tier_b"
    else:
        tier = "tier_a" if (score >= 66 and "supporting_skill_overlap" in rationale) else "tier_b"
    return True, rationale, tier


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--promotion-mode", choices=["legacy", "v2"], default="v2")
    args = parser.parse_args()

    STATE.mkdir(parents=True, exist_ok=True)
    promoted_path = STATE / "promoted_shortlist.ndjson"

    candidates = []
    examined = 0
    for path in sorted(PROCESSED.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        record = payload.get("record", {})
        if record.get("decision") != "watch":
            continue
        examined += 1
        ok, rationale, tier = should_promote(record, promotion_mode=args.promotion_mode)
        if not ok:
            continue
        risk_flags = []
        joined_reasons = " ".join(normalize_text(r) for r in record.get("reasons", []))
        if "sponsorship unknown" in record.get("reasons", []):
            risk_flags.append("sponsorship unknown")
        if "clearance" in joined_reasons or "government" in joined_reasons:
            risk_flags.append("clearance / work authorization check")
        if "thin description" in joined_reasons or "sparse description" in joined_reasons:
            risk_flags.append("description quality low")
        candidates.append({
            "promotedAt": now_iso(),
            "jobId": record.get("jobId"),
            "score": record.get("score"),
            "title": record.get("title"),
            "company": record.get("company"),
            "location": record.get("location"),
            "link": record.get("link"),
            "source": record.get("source"),
            "promotionReasons": rationale,
            "confidenceTier": tier,
            "riskFlags": risk_flags,
        })

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in candidates:
        grouped[group_key(item)].append(item)

    final_items = []
    duplicates_suppressed = 0
    for items in grouped.values():
        items.sort(key=lambda x: (-int(x.get("score", 0)), x.get("confidenceTier", "tier_b")))
        best = items[0]
        final_items.append(best)
        duplicates_suppressed += max(0, len(items) - 1)

    final_items.sort(key=lambda x: (-int(x.get("score", 0)), x.get("company", ""), x.get("title", "")))
    promoted_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in final_items) + ("\n" if final_items else ""),
        encoding="utf-8",
    )

    tier_counts: dict[str, int] = defaultdict(int)
    for item in final_items:
        tier_counts[item.get("confidenceTier", "unknown")] += 1

    print(json.dumps({
        "promotionMode": args.promotion_mode,
        "examinedWatchJobs": examined,
        "promoted": len(final_items),
        "duplicatesSuppressed": duplicates_suppressed,
        "tiers": dict(tier_counts),
        "output": str(promoted_path),
    }, indent=2))


if __name__ == "__main__":
    main()

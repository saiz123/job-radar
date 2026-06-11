#!/usr/bin/env python3
"""Use JobSpy to discover jobs and normalize them into incoming markdown files.

Adds strict pre-ingest filtering so only plausible cybersecurity roles reach the
rest of the pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
INCOMING = ROOT / "incoming"
STATE = ROOT / "state"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "job"


def read_seen_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = payload.get("url")
        if url:
            seen.add(url)
    return seen


def normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[^a-z0-9+]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def compile_phrase_patterns(phrases: list[str]) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for phrase in phrases:
        normalized = normalize_text(phrase)
        if not normalized:
            continue
        token_pattern = r"\s+".join(re.escape(token) for token in normalized.split())
        patterns.append(re.compile(rf"(?<![a-z0-9+]){token_pattern}(?![a-z0-9+])"))
    return patterns


def contains_any(text: str, phrases: list[str]) -> bool:
    return any(pattern.search(text) for pattern in compile_phrase_patterns(phrases))


def description_is_usable(description: str) -> bool:
    desc = (description or "").strip().lower()
    return bool(desc and desc != "nan")


def infer_reason(title: str, company: str, description: str, filters: dict, ingest_mode: str = "legacy") -> str:
    title_norm = normalize_text(title)
    company_norm = normalize_text(company)
    desc_norm = normalize_text(description)

    if contains_any(company_norm, filters.get("companyBlocklist", [])):
        return "company_blocklisted"
    if contains_any(title_norm, filters.get("titleBlocklist", [])):
        return "title_blocklisted"
    if contains_any(desc_norm, filters.get("descriptionBlocklist", [])):
        return "description_blocklisted"
    if contains_any(title_norm, filters.get("experienceRejectPatterns", [])) or contains_any(desc_norm, filters.get("experienceRejectPatterns", [])):
        return "seniority_too_high"
    if contains_any(title_norm + " " + desc_norm, filters.get("hardRejectKeywords", [])):
        return "hard_reject_keyword"
    if not contains_any(title_norm, filters.get("targetTitleKeywords", [])):
        return "title_not_targeted"
    if description_is_usable(description) and not contains_any(desc_norm, filters.get("descriptionRequireAny", [])):
        return "description_missing_cyber_signals"
    if ingest_mode == "v2" and contains_any(company_norm, ["government", "federal", "defense", "national laboratory", "intelligence"]):
        return "government_clearance_risk"
    return "accepted"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest-mode", choices=["legacy", "v2"], default="legacy")
    args = parser.parse_args()

    from jobspy import scrape_jobs  # imported inside venv runtime

    profile = load_json(CONFIG / "profile.json")
    filters = load_json(CONFIG / "filters.json")
    discovered_path = STATE / "discovered_urls.ndjson"
    rejected_path = STATE / "jobspy_rejections.ndjson"
    seen = read_seen_urls(discovered_path)
    INCOMING.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)

    titles = profile["candidate"]["targetTitles"][:3]
    search_term = " OR ".join(titles)
    location = "United States"

    jobs = scrape_jobs(
        site_name=["indeed", "linkedin", "zip_recruiter", "glassdoor"],
        search_term=search_term,
        location=location,
        results_wanted=30,
        hours_old=24,
        country_indeed="usa",
        linkedin_fetch_description=False,
        description_format="markdown",
        verbose=0,
    )

    rows = jobs.to_dict(orient="records") if hasattr(jobs, "to_dict") else []

    summary = {
        "runAt": now_iso(),
        "source": "jobspy",
        "rows": len(rows),
        "newUrls": 0,
        "incomingFiles": 0,
        "rejectedPreIngest": 0,
        "rejectionReasons": {},
    }

    for row in rows:
        url = str(row.get("job_url") or row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        summary["newUrls"] += 1

        title = str(row.get("title") or "Unknown Title").strip()
        company = str(row.get("company") or "Unknown").strip()
        location_val = str(row.get("location") or location).strip()
        salary = str(row.get("min_amount") or row.get("max_amount") or "unknown")
        source = str(row.get("site") or "jobspy").strip()
        description = str(row.get("description") or row.get("job_description") or "").strip()

        rejection_reason = infer_reason(title, company, description, filters, ingest_mode=args.ingest_mode)
        if rejection_reason != "accepted":
            summary["rejectedPreIngest"] += 1
            summary["rejectionReasons"][rejection_reason] = summary["rejectionReasons"].get(rejection_reason, 0) + 1
            append_jsonl(rejected_path, {
                "rejectedAt": now_iso(),
                "source": f"jobspy:{source}",
                "url": url,
                "title": title,
                "company": company,
                "location": location_val,
                "reason": rejection_reason,
            })
            continue

        filename = f"{today_str()}-{slugify(company)}-{slugify(title)}.md"
        path = INCOMING / filename
        body = (
            f"Source: {source}\n"
            f"Apply Link: {url}\n"
            f"Title: {title}\n"
            f"Company: {company}\n"
            f"Location: {location_val}\n"
            f"Salary: {salary}\n\n"
            f"## Description\n{description}\n"
        )
        path.write_text(body, encoding="utf-8")
        summary["incomingFiles"] += 1

        append_jsonl(discovered_path, {
            "discoveredAt": now_iso(),
            "source": f"jobspy:{source}",
            "url": url,
            "title": title,
            "company": company,
        })

    summary["ingestMode"] = args.ingest_mode
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

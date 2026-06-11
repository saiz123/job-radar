#!/usr/bin/env python3
"""File-first job hunting pipeline for Sai's cybersecurity search.

This script intentionally avoids external dependencies.
It reads local intake files, normalizes them, scores them with simple heuristics,
and writes review ledgers plus alert payloads.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from enrich_sponsorship import classify as classify_sponsorship

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
INCOMING = ROOT / "incoming"
STATE = ROOT / "state"
PROCESSED = ROOT / "processed"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
    link = link.rstrip("/")
    return link


def compile_phrase_patterns(phrases: list[str]) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for phrase in phrases:
        normalized = normalize_text(phrase)
        if not normalized:
            continue
        token_pattern = r"\s+".join(re.escape(token) for token in normalized.split())
        patterns.append(re.compile(rf"(?<![a-z0-9+]){token_pattern}(?![a-z0-9+])"))
    return patterns


def contains_phrase(text: str, phrases: list[str]) -> bool:
    return any(pattern.search(text) for pattern in compile_phrase_patterns(phrases))


@dataclass
class JobRecord:
    reviewedAt: str
    jobId: str
    title: str
    company: str
    location: str
    salary: str
    link: str
    source: str
    score: int
    decision: str
    matchedSkills: List[str]
    missingSkills: List[str]
    reasons: List[str]
    notes: str
    sponsorshipStatus: str = "unknown"
    authorizationRisk: str = "medium"


class Pipeline:
    def __init__(self, scoring_mode: str = "v2") -> None:
        self.scoring_mode = scoring_mode
        self.profile = load_json(CONFIG / "profile.json")
        self.filters = load_json(CONFIG / "filters.json")
        self.sponsorship_signals = load_json(CONFIG / "sponsorship_signals.json")
        self.alert_template = (ROOT / "templates" / "telegram_alert.md").read_text(encoding="utf-8")
        self.profile_guardrails = (ROOT / "manager" / "PROFILE_GUARDRAILS.md").read_text(encoding="utf-8")
        self.applications_csv = STATE / "applications.csv"
        STATE.mkdir(parents=True, exist_ok=True)
        PROCESSED.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        files = sorted(INCOMING.glob("*.md")) + sorted(INCOMING.glob("*.txt"))
        files = [f for f in files if f.name.lower() != "readme.md"]
        if not files:
            print("No intake files found.")
            return
        existing_job_keys = self.read_existing_record_keys(STATE / "jobs.ndjson")
        existing_shortlist_keys = self.read_existing_record_keys(STATE / "shortlist.ndjson")
        for path in files:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            structured = self.extract_fields(raw, path)
            if self.is_demo_record(structured):
                print(f"Skipped {path.name}: demo/example fixture")
                continue
            record = self.score_job(structured)
            record_key = self.record_key(record.jobId, record.link)
            if record_key not in existing_job_keys:
                self.append_jsonl(STATE / "jobs.ndjson", asdict(record))
                existing_job_keys.add(record_key)
            if record.score >= self.profile["search"]["alertThreshold"] and record.decision in {"alert", "tailor-ready"}:
                if record_key not in existing_shortlist_keys:
                    self.append_jsonl(STATE / "shortlist.ndjson", asdict(record))
                    existing_shortlist_keys.add(record_key)
            processed_payload = {"sourceFile": path.name, "structured": structured, "record": asdict(record)}
            processed_path = PROCESSED / f"{path.stem}.json"
            processed_path.write_text(json.dumps(processed_payload, indent=2), encoding="utf-8")
            print(f"Processed {path.name}: {record.decision} ({record.score})")

    def extract_fields(self, raw: str, path: Path) -> dict:
        def grab(label: str) -> str:
            pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
            match = pattern.search(raw)
            return match.group(1).strip() if match else ""

        title = grab("Title") or path.stem.replace("-", " ").title()
        company = grab("Company") or "Unknown"
        location = grab("Location") or "Unknown"
        salary = grab("Salary") or "unknown"
        link = grab("Apply Link") or grab("Link") or ""
        source = grab("Source") or "manual"
        description = raw
        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "link": link,
            "source": source,
            "description": description,
        }

    def score_job(self, job: dict) -> JobRecord:
        title_norm = normalize_text(job["title"])
        company_norm = normalize_text(job["company"])
        location_norm = normalize_text(job["location"])
        text_norm = normalize_text(" ".join([job["title"], job["location"], job["description"]]))
        reasons: List[str] = []
        matched: List[str] = []
        missing: List[str] = []
        sponsorship = classify_sponsorship(job, self.sponsorship_signals)

        def has_any(phrases: List[str], haystack: str) -> bool:
            return contains_phrase(haystack, phrases)

        if has_any(self.filters.get("hardRejectKeywords", []), text_norm):
            return JobRecord(
                reviewedAt=now_iso(),
                jobId=self.make_job_id(job),
                title=job["title"],
                company=job["company"],
                location=job["location"],
                salary=job["salary"],
                link=job["link"],
                source=job["source"],
                score=0,
                decision="reject",
                matchedSkills=[],
                missingSkills=[],
                reasons=["hard reject: eligibility / clearance / sponsorship blocker"],
                notes="Rejected by eligibility filter.",
                sponsorshipStatus=sponsorship["sponsorshipStatus"],
                authorizationRisk=sponsorship["authorizationRisk"],
            )

        if has_any(self.filters.get("titleBlocklist", []), title_norm):
            return JobRecord(
                reviewedAt=now_iso(),
                jobId=self.make_job_id(job),
                title=job["title"],
                company=job["company"],
                location=job["location"],
                salary=job["salary"],
                link=job["link"],
                source=job["source"],
                score=5,
                decision="reject",
                matchedSkills=[],
                missingSkills=[],
                reasons=["hard reject: non-cyber title family"],
                notes="Rejected by title filter.",
                sponsorshipStatus=sponsorship["sponsorshipStatus"],
                authorizationRisk=sponsorship["authorizationRisk"],
            )

        score = 0

        explicit_target_titles = [normalize_text(t) for t in self.profile["candidate"]["targetTitles"]]
        target_title_keywords = self.filters.get("targetTitleKeywords", [])
        if any(t in title_norm for t in explicit_target_titles):
            score += 28
            reasons.append("strong title alignment")
        elif has_any(target_title_keywords, title_norm):
            score += 24
            reasons.append("target cyber title match")
        elif any(word in title_norm for word in ["soc", "security analyst", "cybersecurity", "cyber security", "security operations", "infosec"]):
            score += 16
            reasons.append("adjacent cyber title alignment")
        else:
            reasons.append("weak title alignment")

        if any(token in title_norm for token in ["junior", "associate", "entry level", "entry-level", "apprentice", "intern", "i "]):
            score += 16
            reasons.append("title indicates junior level")
        else:
            years_match = re.search(r"(\d)\+?\s+years", text_norm)
            if years_match:
                years = int(years_match.group(1))
                if years <= 2:
                    score += 13
                    reasons.append("entry-level experience fit")
                elif years == 3:
                    score += 7
                    reasons.append("stretch but possible experience fit")
                else:
                    reasons.append("experience ask is high")
            elif "entry level" in text_norm or "entry-level" in text_norm or "associate" in text_norm:
                score += 12
                reasons.append("explicit entry-level fit")
            else:
                score += 6
                reasons.append("experience level unclear")

        if sponsorship["sponsorshipStatus"] == "blocked":
            return JobRecord(
                reviewedAt=now_iso(),
                jobId=self.make_job_id(job),
                title=job["title"],
                company=job["company"],
                location=job["location"],
                salary=job["salary"],
                link=job["link"],
                source=job["source"],
                score=0,
                decision="reject",
                matchedSkills=matched,
                missingSkills=missing,
                reasons=reasons + ["hard reject: sponsorship blocked"],
                notes="Visa sponsorship requirement blocks fit.",
                sponsorshipStatus=sponsorship["sponsorshipStatus"],
                authorizationRisk=sponsorship["authorizationRisk"],
            )

        if sponsorship["sponsorshipStatus"] == "yes":
            score += 12
            reasons.append("sponsorship support indicated")
        elif sponsorship["sponsorshipStatus"] == "likely":
            score += 8
            reasons.append("employer likely sponsorship-friendly")
        elif sponsorship["sponsorshipStatus"] == "likely-no":
            score -= 10
            reasons.append("authorization language increases sponsorship risk")
        elif sponsorship["sponsorshipStatus"] == "unlikely":
            score -= 14
            reasons.append("employer likely unfavorable on sponsorship")
        else:
            score += 4
            reasons.append("sponsorship unknown")

        if "sponsorship" in text_norm:
            if "no future sponsorship" in text_norm or "does not now or in the future require sponsorship" in text_norm:
                return JobRecord(
                    reviewedAt=now_iso(),
                    jobId=self.make_job_id(job),
                    title=job["title"],
                    company=job["company"],
                    location=job["location"],
                    salary=job["salary"],
                    link=job["link"],
                    source=job["source"],
                    score=0,
                    decision="reject",
                    matchedSkills=matched,
                    missingSkills=missing,
                    reasons=reasons + ["hard reject: no sponsorship path"],
                    notes="Visa sponsorship requirement blocks fit.",
                    sponsorshipStatus=sponsorship["sponsorshipStatus"],
                    authorizationRisk=sponsorship["authorizationRisk"],
                )
            if sponsorship["sponsorshipStatus"] not in {"yes", "likely"}:
                score += 2
                reasons.append("sponsorship language present")

        positive_keywords = self.filters["positiveKeywords"]
        found_keywords = [kw for kw in positive_keywords if contains_phrase(text_norm, [kw])]
        matched.extend(sorted(set(found_keywords)))
        score += min(18, len(found_keywords) * 3)
        if found_keywords:
            reasons.append("good skills overlap")
        else:
            if any(token in title_norm for token in ["soc", "security operations", "cybersecurity", "cyber security", "threat analyst"]):
                score += 8
                reasons.append("title suggests cyber relevance despite thin description")
            else:
                reasons.append("limited skills overlap")
                missing.extend(["SIEM", "incident response", "security monitoring"])

        if "remote" in location_norm and "united states" in location_norm:
            score += 10
            reasons.append("remote US fit")
        elif "saint louis" in location_norm or "st louis" in location_norm:
            score += 10
            reasons.append("local fit")
        elif "united states" in location_norm:
            score += 8
            reasons.append("US location fit")
        else:
            score += 4
            reasons.append("location unclear or weaker")

        salary_text = job["salary"].lower()
        salary_numbers = [int(n.replace(",", "")) for n in re.findall(r"\$?([0-9]{2,3},?[0-9]{3})", job["salary"])]
        if salary_numbers:
            if max(salary_numbers) >= self.profile["candidate"]["salaryMinimumUsd"]:
                score += 10
                reasons.append("salary meets target")
            else:
                score += 2
                reasons.append("salary below target")
        elif salary_text in {"unknown", "nan"}:
            score += 5
            reasons.append("salary unknown")

        if any(word in company_norm for word in ["security", "cloud", "mssp", "consulting"]):
            score += 4
            reasons.append("company type may fit target market")
        else:
            score += 2

        if "clearance" in title_norm or "clearance" in text_norm:
            score -= 18
            reasons.append("clearance signal reduces fit")
        if has_any(["staff", "senior", "principal", "manager", "director", "architect", "journeyman"], title_norm):
            score -= 20
            reasons.append("seniority signal reduces fit")
        if has_any(["physical security", "officer", "guard"], title_norm):
            score -= 20
            reasons.append("physical security is off-target")

        if self.scoring_mode == "v2":
            score, reasons, missing = self.apply_v2_adjustments(job, score, reasons, missing, matched)

        score = max(0, min(score, 100))
        decision = "reject" if score < 55 else "watch"
        if score >= self.profile["search"]["alertThreshold"]:
            decision = "alert"
        if score >= self.profile["search"]["tailorThreshold"]:
            decision = "tailor-ready"

        baseline_missing = ["Splunk (lab only)", "Python/PowerShell", "enterprise security tooling"]
        for item in baseline_missing:
            if item.lower() not in text_norm and item not in missing:
                missing.append(item)

        notes = self.build_notes(score, decision, reasons)
        return JobRecord(
            reviewedAt=now_iso(),
            jobId=self.make_job_id(job),
            title=job["title"],
            company=job["company"],
            location=job["location"],
            salary=job["salary"],
            link=job["link"],
            source=job["source"],
            score=score,
            decision=decision,
            matchedSkills=matched,
            missingSkills=missing,
            reasons=reasons,
            notes=notes,
            sponsorshipStatus=sponsorship["sponsorshipStatus"],
            authorizationRisk=sponsorship["authorizationRisk"],
        )

    def apply_v2_adjustments(
        self,
        job: dict,
        score: int,
        reasons: List[str],
        missing: List[str],
        matched: List[str],
    ) -> tuple[int, List[str], List[str]]:
        title_norm = normalize_text(job["title"])
        company_norm = normalize_text(job["company"])
        description = job.get("description", "") or ""
        desc_norm = normalize_text(description)
        has_real_description = bool(description.strip()) and "## description\nnan" not in description.lower() and desc_norm != "nan"

        strong_cyber_title = contains_phrase(title_norm, [
            "soc analyst",
            "security operations analyst",
            "security operations center analyst",
            "cybersecurity analyst",
            "cyber security analyst",
            "associate security specialist",
            "threat analyst",
        ])
        junior_title = contains_phrase(title_norm, [
            "junior",
            "associate",
            "intern",
            "apprentice",
            "entry level",
            "analyst i",
            "soc analyst i",
        ])

        if not has_real_description:
            sparse_penalty = 10
            if strong_cyber_title and junior_title:
                sparse_penalty = 5
                score += 4
                reasons.append("v2: strong junior cyber title offsets thin metadata")
            elif strong_cyber_title:
                sparse_penalty = 7
            score -= sparse_penalty
            reasons.append("v2: sparse description lowers confidence")
            missing.append("full job description unavailable")
        elif len(desc_norm.split()) >= 80:
            score += 4
            reasons.append("v2: full description available")

        if strong_cyber_title and junior_title:
            score += 3
            reasons.append("v2: title stack fits entry cyber target")

        if contains_phrase(company_norm, ["consulting", "staffing", "solutions", "partners", "technologies", "systems"]):
            score -= 4
            reasons.append("v2: recruiting/vendor-style company risk")
        if contains_phrase(company_norm, ["government", "federal", "defense", "national laboratory", "intelligence"]):
            score -= 8
            reasons.append("v2: government/clearance adjacency risk")
            missing.append("work authorization / clearance fit needs manual check")

        if contains_phrase(title_norm, ["engineer ii", "engineer iii", "lead", "manager", "director", "architect"]):
            score -= 8
            reasons.append("v2: title looks above entry level")

        if contains_phrase(title_norm, ["soc analyst i", "associate soc analyst", "junior cybersecurity analyst", "intern cybersecurity analyst"]):
            score += 4
            reasons.append("v2: exact target title variant")

        if matched:
            score += min(6, len(set(matched)))
            reasons.append("v2: matched keyword depth")

        deduped_missing: List[str] = []
        seen_missing: set[str] = set()
        for item in missing:
            lowered = item.lower()
            if lowered in seen_missing:
                continue
            seen_missing.add(lowered)
            deduped_missing.append(item)
        return score, reasons, deduped_missing

    def build_notes(self, score: int, decision: str, reasons: List[str]) -> str:
        return f"Decision: {decision}. Score: {score}. Key reasons: " + "; ".join(reasons[:6])

    def make_job_id(self, job: dict) -> str:
        link_slug = self.link_slug(job.get("link", ""))
        if link_slug:
            return link_slug
        base = f"{job['company']}-{job['title']}-{job['location']}".lower()
        slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
        return slug[:120]

    def link_slug(self, link: str) -> str:
        normalized = normalize_link(link)
        if not normalized:
            return ""
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        return slug[:120]

    def record_key(self, job_id: str, link: str) -> str:
        normalized = normalize_link(link)
        if normalized:
            return f"link::{normalized}"
        return f"job::{job_id}"

    def is_demo_record(self, job: dict) -> bool:
        combined = " ".join([
            normalize_text(job.get("title", "")),
            normalize_text(job.get("company", "")),
            normalize_text(job.get("location", "")),
            normalize_link(job.get("link", "")),
        ])
        markers = ["exampleco", "example com", "example-job", "placeholder", "sample fixture"]
        return any(marker in combined for marker in markers)

    def render_alert(self, record: JobRecord) -> str:
        return (
            self.alert_template
            .replace("{{score}}", str(record.score))
            .replace("{{job_title}}", record.title)
            .replace("{{company}}", record.company)
            .replace("{{location}}", record.location)
            .replace("{{salary}}", record.salary)
            .replace("{{matched_skills}}", ", ".join(record.matchedSkills) or "n/a")
            .replace("{{missing_skills}}", ", ".join(record.missingSkills) or "n/a")
            .replace("{{summary}}", record.notes)
            .replace("{{link}}", record.link or "n/a")
        )

    def append_jsonl(self, path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_existing_record_keys(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        keys: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith('{"_comment"'):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            job_id = payload.get("jobId")
            link = payload.get("link", "")
            if job_id or link:
                keys.add(self.record_key(job_id or "", link))
        return keys


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scoring-mode", choices=["legacy", "v2"], default="v2")
    args = parser.parse_args()
    Pipeline(scoring_mode=args.scoring_mode).run()

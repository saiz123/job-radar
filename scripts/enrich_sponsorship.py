#!/usr/bin/env python3
"""Lightweight sponsorship signal enrichment for job records."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[^a-z0-9+]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    token_pattern = r"\s+".join(re.escape(token) for token in normalized_phrase.split())
    return bool(re.search(rf"(?<![a-z0-9+]){token_pattern}(?![a-z0-9+])", text))


def classify(job: dict, signals: dict | None = None) -> dict:
    signals = signals or load_json(CONFIG / "sponsorship_signals.json")
    company = normalize_text(job.get("company", ""))
    text = normalize_text(" ".join([
        job.get("title", ""),
        job.get("company", ""),
        job.get("description", ""),
    ]))

    for phrase in signals.get("hardReject", []):
        if contains_phrase(text, phrase):
            return {
                "sponsorshipStatus": "blocked",
                "authorizationRisk": "high",
                "manualCheckNeeded": False,
                "signal": phrase,
                "employerConfidence": "high",
            }

    for phrase in signals.get("positive", []):
        if contains_phrase(text, phrase):
            return {
                "sponsorshipStatus": "yes",
                "authorizationRisk": "low",
                "manualCheckNeeded": False,
                "signal": phrase,
                "employerConfidence": "medium",
            }

    for key, value in signals.get("companyHints", {}).items():
        if contains_phrase(company, key):
            risk = "medium"
            if value in {"blocked", "unlikely"}:
                risk = "high"
            elif value in {"yes", "likely"}:
                risk = "low"
            return {
                "sponsorshipStatus": value,
                "authorizationRisk": risk,
                "manualCheckNeeded": value == "unknown",
                "signal": f"company_hint:{key}",
                "employerConfidence": "medium",
            }

    for phrase in signals.get("softNegative", []):
        if contains_phrase(text, phrase):
            return {
                "sponsorshipStatus": "likely-no",
                "authorizationRisk": "high",
                "manualCheckNeeded": True,
                "signal": phrase,
                "employerConfidence": "medium",
            }

    return {
        "sponsorshipStatus": "unknown",
        "authorizationRisk": "medium",
        "manualCheckNeeded": True,
        "signal": "none",
        "employerConfidence": "low",
    }


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", help="Path to processed or structured job JSON")
    args = parser.parse_args()

    payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    job = payload.get("structured") or payload.get("record") or payload
    json.dump(classify(job), sys.stdout, indent=2)
    sys.stdout.write("\n")

#!/usr/bin/env python3
"""Quick benchmark for legacy vs v2 scoring/promotion on current processed corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from run_pipeline import Pipeline
from promote_watch_jobs import should_promote

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "processed"


def load_records() -> list[tuple[str, dict]]:
    items = []
    for path in sorted(PROCESSED.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.append((path.name, payload.get("structured", {})))
    return items


def decision_counts(records: list[dict]) -> dict[str, int]:
    return dict(Counter(record["decision"] for record in records))


def main() -> None:
    corpus = load_records()
    legacy = Pipeline(scoring_mode="legacy")
    v2 = Pipeline(scoring_mode="v2")

    legacy_records = []
    v2_records = []
    changed = []
    for filename, structured in corpus:
        legacy_record = legacy.score_job(structured)
        v2_record = v2.score_job(structured)
        legacy_records.append(legacy_record.__dict__)
        v2_records.append(v2_record.__dict__)
        if legacy_record.score != v2_record.score or legacy_record.decision != v2_record.decision:
            changed.append({
                "file": filename,
                "title": v2_record.title,
                "company": v2_record.company,
                "legacyScore": legacy_record.score,
                "v2Score": v2_record.score,
                "legacyDecision": legacy_record.decision,
                "v2Decision": v2_record.decision,
            })

    legacy_promoted = [r for r in legacy_records if r["decision"] == "watch" and should_promote(r, "legacy")[0]]
    v2_promoted = [r for r in v2_records if r["decision"] == "watch" and should_promote(r, "v2")[0]]

    summary = {
        "records": len(corpus),
        "legacyDecisions": decision_counts(legacy_records),
        "v2Decisions": decision_counts(v2_records),
        "decisionChanges": len(changed),
        "legacyPromotedWatchJobs": len(legacy_promoted),
        "v2PromotedWatchJobs": len(v2_promoted),
        "sampleChanges": changed[:12],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

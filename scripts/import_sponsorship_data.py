#!/usr/bin/env python3
"""Import H-1B/LCA sponsorship history into Job Radar's SQLite spine.

The importer is intentionally CSV-header tolerant because USCIS/DOL exports change
column labels across fiscal years. It accepts one or more H-1B employer CSV files
and/or LCA disclosure CSV files, upserts normalized rows, refreshes company H-1B
summary fields, and recomputes sponsorship class/evidence for currently tracked
jobs.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jobradar_app.config import get_settings  # noqa: E402
from jobradar_app.db import (  # noqa: E402
    _classify_sponsorship,
    _compute_personal_score,
    _json_dumps,
    _normalize_company_name,
    _persist_sponsorship_evidence,
    connect,
    migrate_to_latest,
    new_id,
    now_iso,
)


def _first(row: dict[str, str], names: Iterable[str], default: str = "") -> str:
    folded = {k.strip().casefold().replace(" ", "_").replace("-", "_"): v for k, v in row.items()}
    for name in names:
        value = folded.get(name.casefold().replace(" ", "_").replace("-", "_"))
        if value not in (None, ""):
            return str(value).strip()
    return default


def _int(value: str | None) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").strip() or "0"))
    except ValueError:
        return 0


def _float(value: str | None) -> float | None:
    try:
        raw = str(value or "").replace(",", "").strip()
        return float(raw) if raw else None
    except ValueError:
        return None


def _fy(row: dict[str, str], fallback: int | None) -> int:
    raw = _first(row, ["fiscal_year", "fy", "Fiscal Year", "YEAR"], str(fallback or ""))
    if not raw:
        raise ValueError("missing fiscal year; pass --fiscal-year for files without FY column")
    return _int(raw)


def import_h1b(path: Path, fiscal_year: int | None, source_url: str) -> int:
    settings = get_settings()
    migrate_to_latest(settings)
    loaded_at = now_iso()
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as fh, connect(settings) as conn:
        reader = csv.DictReader(fh)
        for row in reader:
            employer = _first(row, ["employer_name", "petitioner", "petitioner_name", "Employer", "Employer Name"])
            if not employer:
                continue
            fy = _fy(row, fiscal_year)
            normalized = _normalize_company_name(employer)
            city = _first(row, ["city", "employer_city", "Petitioner City"])
            state = _first(row, ["state", "employer_state", "Petitioner State"])
            initial_approval = _int(_first(row, ["initial_approval", "initial_approvals", "approved_initial", "Initial Approval", "Initial Approvals", "Total Initial Approval"])
            )
            continuing_approval = _int(_first(row, ["continuing_approval", "continuing_approvals", "approved_continuing", "Continuing Approval", "Continuing Approvals", "Total Continuing Approval"])
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO h1b_employer_stats (
                  id, fiscal_year, employer_name, employer_name_normalized, city, state, naics,
                  initial_approval, initial_denial, continuing_approval, continuing_denial, loaded_at, source_url
                ) VALUES (
                  COALESCE((SELECT id FROM h1b_employer_stats WHERE fiscal_year = ? AND employer_name_normalized = ? AND COALESCE(city,'') = ? AND COALESCE(state,'') = ?), ?),
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    fy, normalized, city, state, new_id(),
                    fy, employer, normalized, city, state,
                    _first(row, ["naics", "NAICS"]),
                    initial_approval,
                    _int(_first(row, ["initial_denial", "initial_denials", "Initial Denial", "Total Initial Denial"])),
                    continuing_approval,
                    _int(_first(row, ["continuing_denial", "continuing_denials", "Continuing Denial", "Total Continuing Denial"])),
                    loaded_at,
                    source_url or str(path),
                ),
            )
            count += 1
        conn.commit()
    return count


def import_lca(path: Path, fiscal_year: int | None, source_url: str) -> int:
    settings = get_settings()
    migrate_to_latest(settings)
    loaded_at = now_iso()
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as fh, connect(settings) as conn:
        reader = csv.DictReader(fh)
        for row in reader:
            employer = _first(row, ["employer_name", "Employer Name", "EMPLOYER_NAME"])
            if not employer:
                continue
            fy = _fy(row, fiscal_year)
            conn.execute(
                """
                INSERT INTO lca_records (
                  id, fiscal_year, quarter, employer_name_normalized, job_title, soc_code,
                  wage_rate_from, wage_unit, wage_level, worksite_city, worksite_state,
                  case_status, decision_date, loaded_at, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(), fy, _int(_first(row, ["quarter", "qtr"], "0")) or None,
                    _normalize_company_name(employer),
                    _first(row, ["job_title", "Job Title", "JOB_TITLE"]),
                    _first(row, ["soc_code", "SOC Code", "SOC_CODE"]),
                    _float(_first(row, ["wage_rate_from", "Wage Rate From", "WAGE_RATE_OF_PAY_FROM"])),
                    _first(row, ["wage_unit", "Wage Unit", "WAGE_UNIT_OF_PAY"]),
                    _first(row, ["wage_level", "Wage Level", "PW_WAGE_LEVEL"]),
                    _first(row, ["worksite_city", "Worksite City", "WORKSITE_CITY"]),
                    _first(row, ["worksite_state", "Worksite State", "WORKSITE_STATE"]),
                    _first(row, ["case_status", "Case Status", "CASE_STATUS"]),
                    _first(row, ["decision_date", "Decision Date", "DECISION_DATE"]),
                    loaded_at,
                    source_url or str(path),
                ),
            )
            count += 1
        conn.commit()
    return count


def refresh_current_jobs() -> dict[str, int]:
    settings = get_settings()
    migrate_to_latest(settings)
    ts = now_iso()
    changed = 0
    with connect(settings) as conn:
        companies = conn.execute(
            """
            SELECT c.id, c.name_normalized,
                   COALESCE(SUM(h.initial_approval), 0) AS total,
                   MAX(CASE WHEN h.initial_approval > 0 THEN h.fiscal_year END) AS last_fy
            FROM companies c
            LEFT JOIN h1b_employer_stats h ON h.employer_name_normalized = c.name_normalized
            GROUP BY c.id, c.name_normalized
            """
        ).fetchall()
        for company in companies:
            conn.execute(
                "UPDATE companies SET h1b_total_3yr = ?, h1b_last_fy = ?, updated_at = ? WHERE id = ?",
                (int(company["total"] or 0), company["last_fy"], ts, company["id"]),
            )
        jobs = conn.execute(
            """
            SELECT j.*, c.name_normalized
            FROM jobs j JOIN companies c ON c.id = j.company_id
            WHERE COALESCE(j.exclusion_reason, '') NOT IN ('clearance_required', 'citizenship_required', 'no_sponsorship')
            """
        ).fetchall()
        for job in jobs:
            klass, confidence, evidence = _classify_sponsorship(
                conn,
                company_name_normalized=job["name_normalized"],
                description_text=job["description_text"] or "",
                exclusion_reason=job["exclusion_reason"],
                created_at=ts,
            )
            personal_score, tier, score_breakdown, fit_reasons, concerns = _compute_personal_score(
                title_raw=job["title_raw"],
                title_normalized=job["title_normalized"],
                description_text=job["description_text"] or "",
                work_mode=job["work_mode"],
                remote_scope=job["remote_scope"],
                sponsorship_class=klass,
                exclusion_reason=job["exclusion_reason"],
            )
            evidence_id = _persist_sponsorship_evidence(conn, job_id=job["id"], company_id=job["company_id"], evidence=evidence, created_at=ts)
            conn.execute(
                """
                UPDATE jobs
                SET sponsorship_class = ?, sponsorship_confidence = ?, sponsorship_computed_at = ?, sponsorship_rule_version = 1,
                    sponsorship_evidence_id = ?, personal_score = ?, tier = ?, score_breakdown = ?, fit_reasons = ?, concerns = ?, updated_at = ?
                WHERE id = ?
                """,
                (klass, confidence, ts, evidence_id, personal_score, tier, score_breakdown, fit_reasons, concerns, ts, job["id"]),
            )
            changed += 1
        conn.execute(
            "INSERT INTO automation_runs (id, kind, name, argv, exit_code, status, stdout_head, started_at, finished_at, created_at) VALUES (?, 'sponsorship', 'sponsorship-data-refresh', ?, 0, 'ok', ?, ?, ?, ?)",
            (new_id(), _json_dumps(sys.argv), _json_dumps({"jobs_refreshed": changed}), ts, ts, ts),
        )
        conn.commit()
    return {"jobs_refreshed": changed, "companies_refreshed": len(companies)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import H-1B/LCA sponsorship history and refresh tracked jobs")
    parser.add_argument("--h1b", action="append", type=Path, default=[], help="USCIS H-1B employer-data CSV")
    parser.add_argument("--lca", action="append", type=Path, default=[], help="DOL LCA disclosure CSV")
    parser.add_argument("--fiscal-year", type=int, help="Fallback FY for files without an FY column")
    parser.add_argument("--source-url", default="", help="Source URL or label stored with imported records")
    parser.add_argument("--refresh-only", action="store_true", help="Only refresh current companies/jobs from already loaded data")
    args = parser.parse_args()

    imported = {"h1b_rows": 0, "lca_rows": 0}
    if not args.refresh_only:
        for path in args.h1b:
            imported["h1b_rows"] += import_h1b(path, args.fiscal_year, args.source_url)
        for path in args.lca:
            imported["lca_rows"] += import_lca(path, args.fiscal_year, args.source_url)
    refreshed = refresh_current_jobs()
    print({**imported, **refreshed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

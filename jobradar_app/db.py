from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ingest.models import CandidateRecord
from ingest.pipeline import apply_exclusions, dedupe_candidates, normalize_candidate
from .config import Settings, get_settings


def _load_jobs_json(jobs_path: Path) -> list[dict[str, Any]]:
    if not jobs_path.exists():
        return []
    data = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    return jobs if isinstance(jobs, list) else []


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "job"


def _cron_gateway_running(cron_dir: Path) -> tuple[bool, str | None]:
    heartbeat = cron_dir / "ticker_heartbeat"
    if not heartbeat.exists():
        return False, None
    try:
        stamp = float(heartbeat.read_text(encoding="utf-8").strip())
    except Exception:
        return False, None
    age_s = max(0, int(datetime.now(timezone.utc).timestamp() - stamp))
    return age_s <= 180, now_iso()


def _read_scheduler_snapshot(settings: Settings) -> dict[str, Any]:
    cron_dir = settings.cron_dir
    jobs = _load_jobs_json(cron_dir / "jobs.json")
    gateway_running, _ = _cron_gateway_running(cron_dir)
    active = [job for job in jobs if job.get("enabled")]
    next_run = min((job.get("next_run_at") for job in active if job.get("next_run_at")), default=None)
    blocked = sum(1 for job in jobs if job.get("last_status") == "blocked_config")
    return {
        "status": "ok" if gateway_running else "degraded",
        "gateway_running": gateway_running,
        "jobs": len(active),
        "next_run": next_run,
        "blocked_config": blocked,
        "items": [
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "deliver": job.get("deliver"),
                "last_status": job.get("last_status"),
                "last_run_at": job.get("last_run_at"),
                "next_run_at": job.get("next_run_at"),
                "enabled": job.get("enabled"),
            }
            for job in jobs
        ],
    }


def _build_adapter(settings: Settings):
    if not settings.careerops_root or not settings.node_bin:
        return None
    from careerops_adapter import CareerOpsAdapter

    if not settings.careerops_root.exists() or not settings.node_bin.exists():
        return None
    return CareerOpsAdapter(settings.careerops_root, settings.node_bin, settings=settings)


def _build_tracker_addition(*, report_number: int, company: str, role: str, date: str, via: str, status: str, report: str, notes: str):
    from careerops_adapter import TrackerAddition

    return TrackerAddition(
        report_number=report_number,
        date=date,
        company=company,
        via=via,
        role=role,
        score="",
        status=status,
        pdf="",
        report=report,
        notes=notes,
    )


def _read_careerops_snapshot(settings: Settings) -> dict[str, Any]:
    adapter = _build_adapter(settings)
    if adapter is None:
        return {
            "status": "degraded",
            "version": None,
            "onboarding_needed": None,
            "pipeline_pending": 0,
            "last_scan": None,
            "error": "careerops_not_configured",
        }
    try:
        doctor = adapter.doctor_json()
        stats = adapter.stats_json()
        pipeline_pending = 0
        pipeline_path = settings.careerops_root / "data" / "pipeline.md" if settings.careerops_root else None
        if pipeline_path and pipeline_path.exists():
            for line in pipeline_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("- [ ]"):
                    pipeline_pending += 1
        last_scan = None
        scan_runs = adapter.read_scan_runs()
        if scan_runs:
            last_scan = scan_runs[-1].started_at
        onboarding = bool(doctor.get("onboardingNeeded", False))
        warnings = doctor.get("warnings") or []
        return {
            "status": "degraded" if onboarding else "ok",
            "version": None,
            "onboarding_needed": onboarding,
            "pipeline_pending": pipeline_pending,
            "last_scan": last_scan,
            "warnings": warnings,
            "stats": stats,
        }
    except Exception as exc:
        return {
            "status": "error",
            "version": None,
            "onboarding_needed": None,
            "pipeline_pending": 0,
            "last_scan": None,
            "error": str(exc),
        }

MigrationFn = Callable[[sqlite3.Connection, Settings], None]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    ensure_migration_table(conn)
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def mark_applied(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (version, now_iso()),
    )


def mark_unapplied(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))


def get_schema_version(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    with connect(settings) as conn:
        ensure_migration_table(conn)
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
        return int(row[0] or 0)


def existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    current = existing_columns(conn, table)
    for name, ddl in columns.items():
        if name not in current:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def ensure_companies(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
          id TEXT PRIMARY KEY,
          name_raw TEXT NOT NULL,
          name_normalized TEXT NOT NULL,
          domain TEXT,
          logo_url TEXT,
          industry TEXT,
          size_band TEXT,
          hq_city TEXT,
          hq_state TEXT,
          careers_url TEXT,
          ats_platform TEXT,
          ats_slug TEXT,
          is_target INTEGER NOT NULL DEFAULT 0,
          is_blacklisted INTEGER NOT NULL DEFAULT 0,
          priority INTEGER NOT NULL DEFAULT 0,
          research_document_id TEXT,
          h1b_total_3yr INTEGER,
          h1b_last_fy INTEGER,
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    add_missing_columns(
        conn,
        "companies",
        {
            "domain": "TEXT",
            "logo_url": "TEXT",
            "industry": "TEXT",
            "size_band": "TEXT",
            "hq_city": "TEXT",
            "hq_state": "TEXT",
            "careers_url": "TEXT",
            "ats_platform": "TEXT",
            "ats_slug": "TEXT",
            "is_target": "INTEGER NOT NULL DEFAULT 0",
            "is_blacklisted": "INTEGER NOT NULL DEFAULT 0",
            "priority": "INTEGER NOT NULL DEFAULT 0",
            "research_document_id": "TEXT",
            "h1b_total_3yr": "INTEGER",
            "h1b_last_fy": "INTEGER",
            "notes": "TEXT",
        },
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_norm ON companies(name_normalized, COALESCE(hq_state,''))")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_companies_target ON companies(is_target, priority DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_companies_ats ON companies(ats_platform, ats_slug)")


def ensure_scans(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scans (
          id TEXT PRIMARY KEY,
          mode TEXT NOT NULL,
          trigger TEXT NOT NULL,
          status TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          duration_ms INTEGER,
          sources_attempted INTEGER NOT NULL DEFAULT 0,
          sources_succeeded INTEGER NOT NULL DEFAULT 0,
          sources_failed INTEGER NOT NULL DEFAULT 0,
          companies_scanned INTEGER NOT NULL DEFAULT 0,
          jobs_seen INTEGER NOT NULL DEFAULT 0,
          jobs_title_filtered INTEGER NOT NULL DEFAULT 0,
          duplicates_merged INTEGER NOT NULL DEFAULT 0,
          jobs_excluded INTEGER NOT NULL DEFAULT 0,
          jobs_added INTEGER NOT NULL DEFAULT 0,
          jobs_updated INTEGER NOT NULL DEFAULT 0,
          jobs_evaluated INTEGER NOT NULL DEFAULT 0,
          evaluation_queue_depth INTEGER NOT NULL DEFAULT 0,
          errors TEXT,
          warnings TEXT,
          careerops_version TEXT,
          hermes_job_id TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scans_started ON scans(started_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scans_status ON scans(status, started_at DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_sources (
          id TEXT PRIMARY KEY,
          scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
          source_name TEXT NOT NULL,
          ats_platform TEXT,
          status TEXT NOT NULL,
          jobs_found INTEGER NOT NULL DEFAULT 0,
          jobs_new INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 1,
          duration_ms INTEGER,
          http_status INTEGER,
          error TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scan_sources_scan ON scan_sources(scan_id)")


def ensure_jobs(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          dedupe_key TEXT NOT NULL,
          company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
          canonical_url TEXT,
          application_url TEXT NOT NULL,
          source_url TEXT NOT NULL,
          canonical_confidence TEXT NOT NULL DEFAULT 'high',
          source_platform TEXT NOT NULL,
          ats_platform TEXT,
          external_ats_id TEXT,
          discovery_method TEXT NOT NULL DEFAULT 'import',
          title_raw TEXT NOT NULL,
          title_normalized TEXT NOT NULL,
          title_family TEXT,
          seniority_detected TEXT,
          employment_type TEXT,
          location_raw TEXT,
          city TEXT,
          state TEXT,
          country TEXT DEFAULT 'US',
          work_mode TEXT,
          remote_scope TEXT,
          is_st_louis_metro INTEGER NOT NULL DEFAULT 0,
          salary_min INTEGER,
          salary_max INTEGER,
          salary_currency TEXT DEFAULT 'USD',
          salary_period TEXT,
          salary_text TEXT,
          salary_source TEXT,
          salary_confidence REAL,
          posted_at TEXT,
          discovered_at TEXT NOT NULL,
          last_verified_at TEXT,
          closes_at TEXT,
          first_seen_scan_id TEXT REFERENCES scans(id),
          description_text TEXT,
          description_html_sanitized TEXT,
          description_sha256 TEXT,
          description_simhash TEXT,
          skills_required TEXT,
          skills_preferred TEXT,
          experience_min_years INTEGER,
          experience_max_years INTEGER,
          education_requirement TEXT,
          certifications_mentioned TEXT,
          clearance_requirement TEXT,
          citizenship_requirement TEXT,
          sponsorship_class TEXT,
          sponsorship_confidence REAL,
          sponsorship_computed_at TEXT,
          sponsorship_rule_version INTEGER,
          career_ops_score REAL,
          career_ops_report_number INTEGER,
          career_ops_legitimacy TEXT,
          personal_score INTEGER,
          score_version INTEGER,
          score_breakdown TEXT,
          fit_reasons TEXT,
          concerns TEXT,
          priority INTEGER NOT NULL DEFAULT 0,
          tier TEXT,
          status TEXT NOT NULL DEFAULT 'Discovered',
          liveness_status TEXT NOT NULL DEFAULT 'New',
          is_starred INTEGER NOT NULL DEFAULT 0,
          is_archived INTEGER NOT NULL DEFAULT 0,
          exclusion_reason TEXT,
          injection_flag INTEGER NOT NULL DEFAULT 0,
          injection_detail TEXT,
          sponsorship_evidence_id TEXT,
          notified_at TEXT,
          parse_confidence TEXT NOT NULL DEFAULT 'full',
          duplicate_count INTEGER NOT NULL DEFAULT 1,
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    add_missing_columns(conn, "jobs", {
        "canonical_url": "TEXT",
        "canonical_confidence": "TEXT NOT NULL DEFAULT 'high'",
        "ats_platform": "TEXT",
        "external_ats_id": "TEXT",
        "discovery_method": "TEXT NOT NULL DEFAULT 'import'",
        "title_family": "TEXT",
        "seniority_detected": "TEXT",
        "employment_type": "TEXT",
        "city": "TEXT",
        "state": "TEXT",
        "country": "TEXT DEFAULT 'US'",
        "work_mode": "TEXT",
        "remote_scope": "TEXT",
        "is_st_louis_metro": "INTEGER NOT NULL DEFAULT 0",
        "salary_min": "INTEGER",
        "salary_max": "INTEGER",
        "salary_currency": "TEXT DEFAULT 'USD'",
        "salary_period": "TEXT",
        "salary_text": "TEXT",
        "salary_source": "TEXT",
        "salary_confidence": "REAL",
        "posted_at": "TEXT",
        "last_verified_at": "TEXT",
        "closes_at": "TEXT",
        "first_seen_scan_id": "TEXT REFERENCES scans(id)",
        "description_html_sanitized": "TEXT",
        "description_sha256": "TEXT",
        "description_simhash": "TEXT",
        "skills_required": "TEXT",
        "skills_preferred": "TEXT",
        "experience_min_years": "INTEGER",
        "experience_max_years": "INTEGER",
        "education_requirement": "TEXT",
        "certifications_mentioned": "TEXT",
        "clearance_requirement": "TEXT",
        "citizenship_requirement": "TEXT",
        "sponsorship_confidence": "REAL",
        "sponsorship_computed_at": "TEXT",
        "sponsorship_rule_version": "INTEGER",
        "career_ops_score": "REAL",
        "career_ops_report_number": "INTEGER",
        "career_ops_legitimacy": "TEXT",
        "score_version": "INTEGER",
        "score_breakdown": "TEXT",
        "fit_reasons": "TEXT",
        "concerns": "TEXT",
        "priority": "INTEGER NOT NULL DEFAULT 0",
        "tier": "TEXT",
        "liveness_status": "TEXT NOT NULL DEFAULT 'New'",
        "is_starred": "INTEGER NOT NULL DEFAULT 0",
        "is_archived": "INTEGER NOT NULL DEFAULT 0",
        "exclusion_reason": "TEXT",
        "injection_flag": "INTEGER NOT NULL DEFAULT 0",
        "injection_detail": "TEXT",
        "sponsorship_evidence_id": "TEXT",
        "notified_at": "TEXT",
        "parse_confidence": "TEXT NOT NULL DEFAULT 'full'",
        "duplicate_count": "INTEGER NOT NULL DEFAULT 1",
        "notes": "TEXT",
    })
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_dedupe ON jobs(dedupe_key)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_ats ON jobs(ats_platform, external_ats_id) WHERE ats_platform IS NOT NULL AND external_ats_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status_score ON jobs(status, personal_score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_discovered ON jobs(discovered_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_posted ON jobs(posted_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_company ON jobs(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_sponsorship ON jobs(sponsorship_class, sponsorship_confidence DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_liveness ON jobs(liveness_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_triage ON jobs(is_archived, status, personal_score DESC, discovered_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_starred ON jobs(is_starred) WHERE is_starred = 1")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_queue ON jobs(tier, personal_score DESC) WHERE career_ops_report_number IS NULL AND is_archived = 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_sources (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          source_platform TEXT NOT NULL,
          source_url TEXT NOT NULL,
          ats_platform TEXT,
          external_ats_id TEXT,
          discovered_at TEXT NOT NULL DEFAULT '',
          scan_id TEXT REFERENCES scans(id),
          raw_payload_sha256 TEXT,
          raw_payload TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    add_missing_columns(conn, "job_sources", {
        "ats_platform": "TEXT",
        "external_ats_id": "TEXT",
        "discovered_at": "TEXT NOT NULL DEFAULT ''",
        "scan_id": "TEXT REFERENCES scans(id)",
        "raw_payload_sha256": "TEXT",
    })
    conn.execute("CREATE INDEX IF NOT EXISTS ix_job_sources_job ON job_sources(job_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_job_sources_unique ON job_sources(job_id, source_platform, source_url)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_locations (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          city TEXT,
          state TEXT,
          country TEXT,
          is_primary INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_job_locations_job ON job_locations(job_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_snapshots (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          captured_at TEXT NOT NULL,
          capture_reason TEXT NOT NULL,
          content_text TEXT NOT NULL,
          content_html_sanitized TEXT,
          content_sha256 TEXT NOT NULL,
          careerops_jd_path TEXT,
          http_status INTEGER,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_snapshots_job ON job_snapshots(job_id, captured_at DESC)")


def ensure_documents(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
          version_label TEXT NOT NULL,
          title TEXT NOT NULL,
          content_text TEXT,
          file_path TEXT,
          file_sha256 TEXT,
          mime_type TEXT,
          generated_by TEXT,
          ats_keyword_coverage REAL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_docs_job ON documents(job_id, kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_docs_version ON documents(kind, version_label)")


def ensure_applications(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          stage TEXT NOT NULL,
          applied_at TEXT,
          applied_via TEXT,
          resume_document_id TEXT REFERENCES documents(id),
          cover_letter_document_id TEXT REFERENCES documents(id),
          answers_document_id TEXT REFERENCES documents(id),
          careerops_tracker_num INTEGER,
          careerops_state TEXT,
          follow_up_at TEXT,
          last_contact_at TEXT,
          next_action TEXT,
          response_at TEXT,
          rejection_at TEXT,
          offer_at TEXT,
          outcome TEXT,
          salary_offered INTEGER,
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_app_job ON applications(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_app_stage ON applications(stage, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_app_followup ON applications(follow_up_at) WHERE follow_up_at IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_app_applied ON applications(applied_at DESC) WHERE applied_at IS NOT NULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS application_events (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          application_id TEXT REFERENCES applications(id) ON DELETE CASCADE,
          event_type TEXT NOT NULL,
          from_value TEXT,
          to_value TEXT,
          actor TEXT NOT NULL,
          detail TEXT,
          occurred_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    add_missing_columns(conn, "application_events", {
        "application_id": "TEXT REFERENCES applications(id) ON DELETE CASCADE",
        "from_value": "TEXT",
        "to_value": "TEXT",
    })
    conn.execute("CREATE INDEX IF NOT EXISTS ix_events_job ON application_events(job_id, occurred_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_events_type ON application_events(event_type, occurred_at DESC)")


def ensure_sponsorship(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sponsorship_evidence (
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
          company_id TEXT REFERENCES companies(id) ON DELETE CASCADE,
          signal_type TEXT NOT NULL,
          class_implied TEXT NOT NULL,
          confidence REAL NOT NULL,
          evidence_text TEXT NOT NULL,
          quoted_span TEXT,
          char_start INTEGER,
          char_end INTEGER,
          source_url TEXT,
          source_as_of TEXT,
          rule_id TEXT,
          rule_set_version INTEGER,
          derivation TEXT,
          superseded_by TEXT REFERENCES sponsorship_evidence(id),
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_spev_job ON sponsorship_evidence(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_spev_company ON sponsorship_evidence(company_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS h1b_employer_stats (
          id TEXT PRIMARY KEY,
          fiscal_year INTEGER NOT NULL,
          employer_name TEXT NOT NULL,
          employer_name_normalized TEXT NOT NULL,
          city TEXT,
          state TEXT,
          naics TEXT,
          initial_approval INTEGER NOT NULL DEFAULT 0,
          initial_denial INTEGER NOT NULL DEFAULT 0,
          continuing_approval INTEGER NOT NULL DEFAULT 0,
          continuing_denial INTEGER NOT NULL DEFAULT 0,
          loaded_at TEXT NOT NULL,
          source_url TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_h1b_unique ON h1b_employer_stats(fiscal_year, employer_name_normalized, COALESCE(city,''), COALESCE(state,''))")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_h1b_lookup ON h1b_employer_stats(employer_name_normalized, state, fiscal_year DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lca_records (
          id TEXT PRIMARY KEY,
          fiscal_year INTEGER NOT NULL,
          quarter INTEGER,
          employer_name_normalized TEXT NOT NULL,
          job_title TEXT,
          soc_code TEXT,
          wage_rate_from REAL,
          wage_unit TEXT,
          wage_level TEXT,
          worksite_city TEXT,
          worksite_state TEXT,
          case_status TEXT,
          decision_date TEXT,
          loaded_at TEXT NOT NULL,
          source_url TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_lca_lookup ON lca_records(employer_name_normalized, soc_code, fiscal_year DESC)")


def ensure_contacts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
          id TEXT PRIMARY KEY,
          company_id TEXT REFERENCES companies(id) ON DELETE SET NULL,
          name TEXT NOT NULL,
          title TEXT,
          email TEXT,
          profile_url TEXT,
          relationship TEXT,
          source TEXT,
          last_contacted_at TEXT,
          next_follow_up_at TEXT,
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_contacts_company ON contacts(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_contacts_followup ON contacts(next_follow_up_at) WHERE next_follow_up_at IS NOT NULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_links (
          id TEXT PRIMARY KEY,
          contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
          job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
          application_id TEXT REFERENCES applications(id) ON DELETE CASCADE,
          role_in_process TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_contact_links_unique ON contact_links(contact_id, COALESCE(job_id,''), COALESCE(application_id,''))")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interviews (
          id TEXT PRIMARY KEY,
          application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
          round_type TEXT NOT NULL,
          scheduled_at TEXT,
          duration_min INTEGER,
          format TEXT,
          location_or_link TEXT,
          interviewer_contact_ids TEXT,
          prep_document_id TEXT REFERENCES documents(id),
          notes_document_id TEXT REFERENCES documents(id),
          outcome TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_interviews_app ON interviews(application_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_interviews_sched ON interviews(scheduled_at) WHERE scheduled_at IS NOT NULL")


def ensure_automation(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_runs (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          name TEXT NOT NULL,
          scan_id TEXT REFERENCES scans(id) ON DELETE SET NULL,
          job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
          argv TEXT,
          exit_code INTEGER,
          duration_ms INTEGER,
          stdout_head TEXT,
          stderr_head TEXT,
          status TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_autoruns_started ON automation_runs(started_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_autoruns_status ON automation_runs(status, started_at DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_cache (
          id TEXT PRIMARY KEY,
          metric TEXT NOT NULL,
          window_label TEXT NOT NULL,
          score_version INTEGER NOT NULL,
          payload TEXT NOT NULL,
          computed_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_analytics_key ON analytics_cache(metric, window_label, score_version)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_failures (
          id TEXT PRIMARY KEY,
          scan_id TEXT REFERENCES scans(id) ON DELETE CASCADE,
          stage TEXT NOT NULL,
          error TEXT NOT NULL,
          raw_payload TEXT,
          resolved INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        )
        """
    )


def ensure_preferences(conn: sqlite3.Connection, settings: Settings) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          profile_json TEXT NOT NULL,
          scoring_version INTEGER NOT NULL DEFAULT 1,
          notification_threshold INTEGER NOT NULL DEFAULT 85,
          auto_package_threshold INTEGER NOT NULL DEFAULT 90,
          max_evaluations_per_run INTEGER NOT NULL DEFAULT 8,
          max_evaluations_per_day INTEGER NOT NULL DEFAULT 20,
          max_auto_packages_per_day INTEGER NOT NULL DEFAULT 3,
          scan_timeout_minutes INTEGER NOT NULL DEFAULT 45,
          experience_ceiling_years INTEGER NOT NULL DEFAULT 3,
          max_job_age_days INTEGER NOT NULL DEFAULT 45,
          oflc_enrichment_enabled INTEGER NOT NULL DEFAULT 0,
          last_seen_at TEXT,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_filters (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          query_json TEXT NOT NULL,
          is_pinned INTEGER NOT NULL DEFAULT 0,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        )
        """
    )
    profile_path = settings.import_dir.parent / "config" / "profile.json"
    profile_json = "{}"
    if profile_path.exists():
        profile_json = profile_path.read_text(encoding="utf-8")
    conn.execute(
        """
        INSERT INTO user_preferences(
          id, profile_json, notification_threshold, auto_package_threshold,
          max_evaluations_per_run, max_evaluations_per_day, max_auto_packages_per_day,
          scan_timeout_minutes, experience_ceiling_years, max_job_age_days, updated_at
        ) VALUES (1, ?, 85, 90, 8, 20, 3, 45, 3, 45, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (profile_json, now_iso()),
    )


def ensure_auth(conn: sqlite3.Connection, settings: Settings) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_users (
          id TEXT PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          totp_secret TEXT,
          webauthn_credentials TEXT,
          failed_attempts INTEGER NOT NULL DEFAULT 0,
          locked_until TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL,
          user_agent_hash TEXT,
          ip_hash TEXT,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          last_used_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id, expires_at)")
    conn.execute(
        """
        INSERT INTO app_users(id, username, password_hash, created_at, updated_at)
        VALUES ('default-user', 'sai', ?, ?, ?)
        ON CONFLICT(username) DO NOTHING
        """,
        (settings.password_hash, now_iso(), now_iso()),
    )


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM jobs_fts_map")
    conn.execute("DELETE FROM jobs_fts")
    rows = conn.execute(
        "SELECT jobs.id, jobs.title_raw, companies.name_raw, COALESCE(jobs.description_text,''), COALESCE(jobs.skills_required,''), COALESCE(jobs.notes,'') FROM jobs JOIN companies ON companies.id = jobs.company_id"
    ).fetchall()
    for row in rows:
        cursor = conn.execute(
            "INSERT INTO jobs_fts(job_id, title, company, description, skills, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3], row[4], row[5]),
        )
        conn.execute(
            "INSERT OR REPLACE INTO jobs_fts_map(job_id, fts_rowid) VALUES (?, ?)",
            (row[0], cursor.lastrowid),
        )
    conn.execute("INSERT INTO jobs_fts(jobs_fts) VALUES('optimize')")


def ensure_fts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
          job_id UNINDEXED,
          title, company, description, skills, notes,
          tokenize='porter unicode61 remove_diacritics 2'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs_fts_map (
          job_id TEXT PRIMARY KEY,
          fts_rowid INTEGER NOT NULL UNIQUE
        )
        """
    )
    rebuild_fts(conn)


def ensure_resume_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_bases (
          id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          source_path TEXT,
          content_text TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_variants (
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
          base_id TEXT REFERENCES resume_bases(id) ON DELETE SET NULL,
          label TEXT NOT NULL,
          content_text TEXT,
          source_text TEXT,
          pdf_document_id TEXT REFERENCES documents(id),
          compile_status TEXT,
          compiled_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ats_analyses (
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
          resume_variant_id TEXT REFERENCES resume_variants(id) ON DELETE SET NULL,
          score REAL,
          keyword_coverage REAL,
          phase TEXT,
          detail_json TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_suggestions (
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
          resume_variant_id TEXT REFERENCES resume_variants(id) ON DELETE SET NULL,
          suggestion_text TEXT NOT NULL,
          term TEXT,
          rationale TEXT,
          is_safe INTEGER,
          status TEXT,
          applied_at TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    add_missing_columns(conn, "resume_variants", {
        "source_text": "TEXT",
        "compile_status": "TEXT",
        "compiled_at": "TEXT",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "version_label": "TEXT",
        "parent_variant_id": "TEXT REFERENCES resume_variants(id) ON DELETE SET NULL",
        "is_locked": "INTEGER NOT NULL DEFAULT 0",
    })
    add_missing_columns(conn, "ats_analyses", {"phase": "TEXT"})
    add_missing_columns(conn, "resume_suggestions", {
        "term": "TEXT",
        "rationale": "TEXT",
        "is_safe": "INTEGER",
        "status": "TEXT",
        "applied_at": "TEXT",
    })
    add_missing_columns(conn, "applications", {"resume_variant_id": "TEXT REFERENCES resume_variants(id) ON DELETE SET NULL"})


def migration_001(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_companies(conn)
    ensure_scans(conn)


def migration_002(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_jobs(conn)


def migration_003(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_documents(conn)


def migration_004(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_applications(conn)


def migration_005(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_sponsorship(conn)


def migration_006(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_contacts(conn)


def migration_007(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_automation(conn)


def migration_008(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_preferences(conn, settings)


def migration_009(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_auth(conn, settings)


def migration_010(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_fts(conn)


def migration_011(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_resume_tables(conn)


def migration_012(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_resume_tables(conn)


def migration_013(conn: sqlite3.Connection, settings: Settings) -> None:
    ensure_resume_tables(conn)


def drop_if_exists(conn: sqlite3.Connection, name: str, kind: str = "table") -> None:
    conn.execute(f"DROP {kind} IF EXISTS {name}")


def downgrade_011(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "resume_suggestions")
    drop_if_exists(conn, "ats_analyses")
    drop_if_exists(conn, "resume_variants")
    drop_if_exists(conn, "resume_bases")


def downgrade_012(conn: sqlite3.Connection, settings: Settings) -> None:
    return None


def downgrade_013(conn: sqlite3.Connection, settings: Settings) -> None:
    return None


def downgrade_010(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "jobs_fts", kind="table")
    drop_if_exists(conn, "jobs_fts_map")


def downgrade_009(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "sessions")
    drop_if_exists(conn, "app_users")


def downgrade_008(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "saved_filters")
    drop_if_exists(conn, "user_preferences")


def downgrade_007(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "ingest_failures")
    drop_if_exists(conn, "analytics_cache")
    drop_if_exists(conn, "automation_runs")


def downgrade_006(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "interviews")
    drop_if_exists(conn, "contact_links")
    drop_if_exists(conn, "contacts")


def downgrade_005(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "lca_records")
    drop_if_exists(conn, "h1b_employer_stats")
    drop_if_exists(conn, "sponsorship_evidence")


def downgrade_004(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "application_events")
    drop_if_exists(conn, "applications")


def downgrade_003(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "documents")


def downgrade_002(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "job_snapshots")
    drop_if_exists(conn, "job_locations")
    drop_if_exists(conn, "job_sources")
    drop_if_exists(conn, "jobs")


def downgrade_001(conn: sqlite3.Connection, settings: Settings) -> None:
    drop_if_exists(conn, "scan_sources")
    drop_if_exists(conn, "scans")
    drop_if_exists(conn, "companies")


MIGRATIONS: list[tuple[int, MigrationFn, MigrationFn]] = [
    (1, migration_001, downgrade_001),
    (2, migration_002, downgrade_002),
    (3, migration_003, downgrade_003),
    (4, migration_004, downgrade_004),
    (5, migration_005, downgrade_005),
    (6, migration_006, downgrade_006),
    (7, migration_007, downgrade_007),
    (8, migration_008, downgrade_008),
    (9, migration_009, downgrade_009),
    (10, migration_010, downgrade_010),
    (11, migration_011, downgrade_011),
    (12, migration_012, downgrade_012),
    (13, migration_013, downgrade_013),
]


def migrate_to_latest(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with connect(settings) as conn:
        ensure_migration_table(conn)
        done = applied_versions(conn)
        for version, upgrade, _ in MIGRATIONS:
            if version in done:
                continue
            conn.execute("PRAGMA foreign_keys=OFF")
            upgrade(conn, settings)
            conn.execute("PRAGMA foreign_keys=ON")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError(f"foreign_key_check failed after migration {version:03d}")
            mark_applied(conn, version)
        conn.commit()


def downgrade_to_version(target_version: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with connect(settings) as conn:
        ensure_migration_table(conn)
        current = get_schema_version(settings)
        for version, _, downgrade in reversed(MIGRATIONS):
            if version <= target_version or version > current:
                continue
            conn.execute("PRAGMA foreign_keys=OFF")
            downgrade(conn, settings)
            conn.execute("PRAGMA foreign_keys=ON")
            mark_unapplied(conn, version)
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign_key_check failed after downgrade")
        conn.commit()


def init_db(settings: Settings | None = None) -> None:
    migrate_to_latest(settings)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _company_lookup_or_create(conn: sqlite3.Connection, company_name_raw: str, now: str) -> str:
    company_norm = company_name_raw.casefold().strip()
    row = conn.execute("SELECT id FROM companies WHERE name_normalized = ?", (company_norm,)).fetchone()
    if row is not None:
        return str(row[0])
    company_id = new_id()
    conn.execute(
        "INSERT INTO companies (id, name_raw, name_normalized, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (company_id, company_name_raw, company_norm, now, now),
    )
    return company_id


def _record_event(conn: sqlite3.Connection, *, job_id: str, event_type: str, actor: str, detail: dict[str, Any]) -> None:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO application_events (id, job_id, event_type, actor, detail, occurred_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id(), job_id, event_type, actor, _json_dumps(detail), ts, ts),
    )


def _scan_source_name(source_platform: str, source_url: str) -> str:
    if source_url:
        parsed = source_url.split("//", 1)[-1]
        host = parsed.split("/", 1)[0]
        if host:
            return host
    return source_platform


def _insert_scan_source(
    conn: sqlite3.Connection,
    *,
    scan_id: str,
    source_platform: str,
    source_url: str,
    status: str,
    jobs_found: int,
    jobs_new: int,
    error: str | None,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO scan_sources (
          id, scan_id, source_name, ats_platform, status, jobs_found, jobs_new, attempts, error, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            new_id(),
            scan_id,
            _scan_source_name(source_platform, source_url),
            source_platform,
            status,
            jobs_found,
            jobs_new,
            error,
            created_at,
        ),
    )


def _sum_recent_h1b_approvals(conn: sqlite3.Connection, employer_name_normalized: str) -> tuple[int, int | None]:
    rows = conn.execute(
        """
        SELECT fiscal_year, initial_approval
        FROM h1b_employer_stats
        WHERE employer_name_normalized = ?
        ORDER BY fiscal_year DESC
        LIMIT 3
        """,
        (employer_name_normalized,),
    ).fetchall()
    if not rows:
        return 0, None
    return sum(int(row["initial_approval"] or 0) for row in rows), int(rows[0]["fiscal_year"])


def _classify_sponsorship(
    conn: sqlite3.Connection,
    *,
    company_name_normalized: str,
    description_text: str,
    exclusion_reason: str | None,
    created_at: str,
) -> tuple[str, float, dict[str, Any]]:
    if exclusion_reason in {"clearance_required", "citizenship_required", "no_sponsorship"}:
        return exclusion_reason, 0.97, {
            "signal_type": "posting_text",
            "class_implied": exclusion_reason,
            "confidence": 0.97,
            "evidence_text": description_text,
            "quoted_span": description_text,
            "char_start": 0,
            "char_end": len(description_text),
            "source_as_of": created_at,
            "rule_id": exclusion_reason,
            "rule_set_version": 1,
            "derivation": {"basis": "hard_restriction_text"},
        }

    approvals, latest_fy = _sum_recent_h1b_approvals(conn, company_name_normalized)
    if approvals >= 10 and latest_fy is not None:
        klass = "likely"
        confidence = 0.68
    elif approvals >= 5:
        klass = "historically_possible"
        confidence = 0.60
    elif approvals >= 1:
        klass = "historically_possible"
        confidence = 0.45
    else:
        klass = "not_stated"
        confidence = 0.20

    evidence_text = (
        f"USCIS H-1B Employer Data Hub, FY{latest_fy}: {approvals} initial approvals."
        if approvals and latest_fy is not None
        else "No evidence found in posting text or loaded H-1B history."
    )
    return klass, confidence, {
        "signal_type": "h1b_history" if approvals else "null_result",
        "class_implied": klass,
        "confidence": confidence,
        "evidence_text": evidence_text,
        "source_as_of": created_at,
        "rule_id": "h1b_history",
        "rule_set_version": 1,
        "derivation": {"approvals_last_3y": approvals, "latest_fiscal_year": latest_fy},
    }


def _persist_sponsorship_evidence(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    company_id: str,
    evidence: dict[str, Any],
    created_at: str,
) -> str:
    evidence_id = new_id()
    conn.execute(
        """
        INSERT INTO sponsorship_evidence (
          id, job_id, company_id, signal_type, class_implied, confidence, evidence_text,
          quoted_span, char_start, char_end, source_as_of, rule_id, rule_set_version, derivation, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            job_id,
            company_id,
            evidence["signal_type"],
            evidence["class_implied"],
            evidence["confidence"],
            evidence["evidence_text"],
            evidence.get("quoted_span"),
            evidence.get("char_start"),
            evidence.get("char_end"),
            evidence.get("source_as_of"),
            evidence.get("rule_id"),
            evidence.get("rule_set_version", 1),
            _json_dumps(evidence.get("derivation", {})),
            created_at,
        )
    )
    return evidence_id


def _compute_personal_score(
    *,
    title_raw: str,
    title_normalized: str,
    description_text: str,
    work_mode: str,
    remote_scope: str | None,
    sponsorship_class: str,
    exclusion_reason: str | None,
) -> tuple[int, str, str, str, str]:
    if exclusion_reason in {"clearance_required", "citizenship_required", "no_sponsorship"}:
        breakdown = [
            {
                "dimension": "hard_gate",
                "weight": -40,
                "earned": 0,
                "evidence": exclusion_reason,
            }
        ]
        return 0, "D", _json_dumps(breakdown), _json_dumps([]), _json_dumps([exclusion_reason])

    score = 0
    fit_reasons: list[str] = []
    concerns: list[str] = []
    breakdown: list[dict[str, Any]] = []
    title_fold = title_normalized.casefold()
    text = description_text.casefold()

    if "soc analyst" in title_fold or "security analyst" in title_fold:
        score += 16
        fit_reasons.append("Role/title alignment with SOC analyst path")
        breakdown.append({"dimension": "role_match", "weight": 16, "earned": 16, "evidence": title_raw})
    if any(term in text for term in ["soc", "siem", "triage", "alert monitoring", "splunk", "sentinel"]):
        score += 20
        fit_reasons.append("SOC and SIEM language present")
        breakdown.append({"dimension": "soc_relevance", "weight": 20, "earned": 20, "evidence": "SOC/SIEM terms in posting"})
    if "security+" in text or "compTIA security+".casefold() in text or "security+ or equivalent" in text:
        score += 5
        fit_reasons.append("Security+ explicitly requested")
        breakdown.append({"dimension": "certification", "weight": 5, "earned": 5, "evidence": "Security+ or equivalent"})
    if "python" in text:
        score += 5
        fit_reasons.append("Python scripting mentioned")
        breakdown.append({"dimension": "project_relevance", "weight": 5, "earned": 5, "evidence": "Python scripting"})
    if work_mode == "remote" and remote_scope == "US":
        score += 8
        fit_reasons.append("Remote - United States")
        breakdown.append({"dimension": "location_fit", "weight": 8, "earned": 8, "evidence": "Remote - US"})

    sponsorship_points = {
        "confirmed": 12,
        "likely": 8,
        "historically_possible": 4,
        "unclear": 0,
        "not_stated": 0,
        "no_sponsorship": -40,
        "citizenship_required": -40,
        "clearance_required": -40,
        "federal_restricted": -40,
    }.get(sponsorship_class, 0)
    score += sponsorship_points
    breakdown.append({"dimension": "sponsorship", "weight": sponsorship_points, "earned": sponsorship_points, "evidence": sponsorship_class})
    if sponsorship_class in {"not_stated", "unclear"}:
        concerns.append("Sponsorship not stated")
    elif sponsorship_class in {"historically_possible", "likely"}:
        concerns.append(f"Sponsorship inferred from history: {sponsorship_class}")

    score = max(0, min(100, score))
    if score >= 90:
        tier = "A+"
    elif score >= 75:
        tier = "A"
    elif score >= 54:
        tier = "B"
    elif score >= 40:
        tier = "C"
    else:
        tier = "D"
    if not concerns:
        concerns.append("No major concerns detected from deterministic pass")
    return score, tier, _json_dumps(breakdown), _json_dumps(fit_reasons), _json_dumps(concerns)


def _serialize_scan(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def get_scan(scan_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        scan = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if scan is None:
            raise KeyError(scan_id)
        payload = _serialize_scan(scan)
        payload["scan_sources"] = [
            _serialize_scan(row)
            for row in conn.execute("SELECT * FROM scan_sources WHERE scan_id = ? ORDER BY created_at ASC", (scan_id,)).fetchall()
        ]
        return payload


def get_latest_scan(settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute("SELECT id FROM scans ORDER BY started_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
    return get_scan(str(row["id"]), settings)


def list_scans(limit: int = 20, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM scans ORDER BY started_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return {"items": [_serialize_scan(row) for row in rows]}


def _loads_json_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except Exception:
        return []
    return value if isinstance(value, list) else []


def _serialize_job_list_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "company": {
            "id": row["company_id"],
            "name": row["company_name"],
            "domain": row["domain"],
            "logo_url": row["logo_url"],
        },
        "title": row["title_raw"],
        "location": {
            "raw": row["location_raw"],
            "city": row["city"],
            "state": row["state"],
            "work_mode": row["work_mode"],
            "remote_scope": row["remote_scope"],
            "is_st_louis_metro": bool(row["is_st_louis_metro"]),
        },
        "scores": {
            "personal": row["personal_score"],
            "career_ops": row["career_ops_score"],
            "version": row["score_version"],
            "tier": row["tier"],
        },
        "sponsorship": {
            "class": row["sponsorship_class"],
            "confidence": row["sponsorship_confidence"],
            "evidence_summary": "; ".join(_loads_json_array(row["concerns"])),
        },
        "status": row["status"],
        "liveness_status": row["liveness_status"],
        "is_starred": bool(row["is_starred"]),
        "injection_flag": bool(row["injection_flag"]),
        "sources_count": row["sources_count"],
        "application_url": row["application_url"],
        "detail_url": f"/jobs/{row['id']}",
        "discovered_at": row["discovered_at"],
        "posted_at": row["posted_at"],
    }


def list_jobs(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            """
            SELECT
              jobs.*,
              companies.name_raw AS company_name,
              companies.domain AS domain,
              companies.logo_url AS logo_url,
              COUNT(job_sources.id) AS sources_count
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            LEFT JOIN job_sources ON job_sources.job_id = jobs.id
            WHERE jobs.is_archived = 0
            GROUP BY jobs.id
            ORDER BY jobs.personal_score DESC, jobs.discovered_at DESC
            """
        ).fetchall()
        return {
            "items": [_serialize_job_list_item(row) for row in rows],
            "total": len(rows),
        }


def get_job(job_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute(
            """
            SELECT jobs.*, companies.name_raw AS company_name, companies.domain, companies.logo_url
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        sources = conn.execute(
            "SELECT id, source_platform, source_url, ats_platform, external_ats_id, discovered_at, scan_id FROM job_sources WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        ).fetchall()
        snapshots = conn.execute(
            "SELECT id, captured_at, capture_reason, content_text, content_html_sanitized, content_sha256, created_at FROM job_snapshots WHERE job_id = ? ORDER BY captured_at DESC",
            (job_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT id, event_type, from_value, to_value, actor, detail, occurred_at, created_at FROM application_events WHERE job_id = ? ORDER BY occurred_at DESC",
            (job_id,),
        ).fetchall()
        application = conn.execute(
            "SELECT * FROM applications WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        documents = conn.execute(
            "SELECT * FROM documents WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        ).fetchall()
        evidence = conn.execute(
            "SELECT id, signal_type, class_implied, confidence, evidence_text, quoted_span, char_start, char_end, source_url, source_as_of, rule_id, rule_set_version, derivation, created_at FROM sponsorship_evidence WHERE job_id = ? ORDER BY created_at DESC",
            (job_id,),
        ).fetchall()
    return {
        "id": row["id"],
        "title": row["title_raw"],
        "company": {
            "id": row["company_id"],
            "name": row["company_name"],
            "domain": row["domain"],
            "logo_url": row["logo_url"],
        },
        "status": row["status"],
        "liveness_status": row["liveness_status"],
        "application_url": row["application_url"],
        "source_url": row["source_url"],
        "location": {
            "raw": row["location_raw"],
            "city": row["city"],
            "state": row["state"],
            "work_mode": row["work_mode"],
            "remote_scope": row["remote_scope"],
            "is_st_louis_metro": bool(row["is_st_louis_metro"]),
        },
        "scores": {
            "personal": row["personal_score"],
            "career_ops": row["career_ops_score"],
            "version": row["score_version"],
            "tier": row["tier"],
        },
        "sponsorship": {
            "class": row["sponsorship_class"],
            "confidence": row["sponsorship_confidence"],
            "evidence_summary": "; ".join(_loads_json_array(row["concerns"])),
        },
        "score_breakdown": _loads_json_array(row["score_breakdown"]),
        "fit_reasons": _loads_json_array(row["fit_reasons"]),
        "concerns": _loads_json_array(row["concerns"]),
        "application": _serialize_application(application),
        "sources": [dict(item) for item in sources],
        "snapshots": [dict(item) for item in snapshots],
        "events": [dict(item) for item in events],
        "sponsorship_evidence": [dict(item) for item in evidence],
        "documents": [_serialize_document(item) for item in documents],
        "contacts": [],
        "description_text": row["description_text"],
        "description_html_sanitized": row["description_html_sanitized"],
    }


PIPELINE_STAGES = [
    "Discovered",
    "Reviewing",
    "Saved",
    "Prepping",
    "ReadyToApply",
    "Applied",
    "Screening",
    "Responded",
    "Interview",
    "Offer",
    "Rejected",
    "Withdrawn",
    "Archived",
]


def _serialize_document(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "version_label": row["version_label"],
        "file_path": row["file_path"],
        "mime_type": row["mime_type"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }




def _variant_version_label(label: str, revision: int) -> str:
    return f"{_slugify(label) or 'resume-variant'}-v{max(1, int(revision))}"


def _fork_resume_variant(conn: sqlite3.Connection, variant: sqlite3.Row, *, actor: str, reason: str) -> sqlite3.Row:
    ts = now_iso()
    next_revision = int(variant["revision"] or 1) + 1
    new_variant_id = new_id()
    new_label = f"{variant['label']} v{next_revision}"
    conn.execute(
        "INSERT INTO resume_variants (id, job_id, base_id, label, content_text, source_text, pdf_document_id, compile_status, compiled_at, created_at, updated_at, revision, version_label, parent_variant_id, is_locked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_variant_id,
            variant["job_id"],
            variant["base_id"],
            new_label,
            variant["content_text"],
            variant["source_text"],
            None,
            "draft",
            None,
            ts,
            ts,
            next_revision,
            _variant_version_label(new_label, next_revision),
            variant["id"],
            0,
        ),
    )
    suggestions = conn.execute("SELECT * FROM resume_suggestions WHERE resume_variant_id = ? ORDER BY created_at ASC", (variant["id"],)).fetchall()
    for suggestion in suggestions:
        conn.execute(
            "INSERT INTO resume_suggestions (id, job_id, resume_variant_id, suggestion_text, term, rationale, is_safe, status, applied_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), suggestion["job_id"], new_variant_id, suggestion["suggestion_text"], suggestion["term"], suggestion["rationale"], suggestion["is_safe"], "pending", None, ts),
        )
    _record_event(conn, job_id=str(variant["job_id"]), event_type="resume.revision_created", actor=actor, detail={"from_variant_id": variant["id"], "variant_id": new_variant_id, "reason": reason, "revision": next_revision})
    return conn.execute("SELECT * FROM resume_variants WHERE id = ?", (new_variant_id,)).fetchone()


def _active_resume_variant_for_write(conn: sqlite3.Connection, variant_id: str, *, actor: str, reason: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM resume_variants WHERE id = ?", (variant_id,)).fetchone()
    if row is None:
        raise KeyError(variant_id)
    if int(row["is_locked"] or 0):
        return _fork_resume_variant(conn, row, actor=actor, reason=reason)
    return row


def _serialize_application(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "stage": row["stage"],
        "applied_at": row["applied_at"],
        "applied_via": row["applied_via"],
        "resume_document_id": row["resume_document_id"],
        "resume_variant_id": row["resume_variant_id"],
        "cover_letter_document_id": row["cover_letter_document_id"],
        "answers_document_id": row["answers_document_id"],
        "careerops_tracker_num": row["careerops_tracker_num"],
        "careerops_state": row["careerops_state"],
        "follow_up_at": row["follow_up_at"],
        "last_contact_at": row["last_contact_at"],
        "next_action": row["next_action"],
        "response_at": row["response_at"],
        "rejection_at": row["rejection_at"],
        "offer_at": row["offer_at"],
        "outcome": row["outcome"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_applications(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            """
            SELECT
              applications.*,
              jobs.title_raw AS job_title,
              jobs.status AS job_status,
              companies.id AS company_id,
              companies.name_raw AS company_name,
              resume_doc.title AS resume_title,
              resume_doc.version_label AS resume_version_label,
              cover_doc.title AS cover_title,
              answers_doc.title AS answers_title
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            JOIN companies ON companies.id = jobs.company_id
            LEFT JOIN documents AS resume_doc ON resume_doc.id = applications.resume_document_id
            LEFT JOIN documents AS cover_doc ON cover_doc.id = applications.cover_letter_document_id
            LEFT JOIN documents AS answers_doc ON answers_doc.id = applications.answers_document_id
            ORDER BY COALESCE(applications.applied_at, applications.updated_at, applications.created_at) DESC
            """
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = _serialize_application(row) or {}
        payload["job"] = {
            "id": row["job_id"],
            "title": row["job_title"],
            "status": row["job_status"],
        }
        payload["company"] = {
            "id": row["company_id"],
            "name": row["company_name"],
        }
        payload["resume"] = {
            "document_id": row["resume_document_id"],
            "title": row["resume_title"],
            "version_label": row["resume_version_label"],
        } if row["resume_document_id"] else None
        payload["resume_variant"] = get_resume_variant(str(row["resume_variant_id"]), settings) if row["resume_variant_id"] else None
        payload["cover_letter"] = {
            "document_id": row["cover_letter_document_id"],
            "title": row["cover_title"],
        } if row["cover_letter_document_id"] else None
        payload["answers"] = {
            "document_id": row["answers_document_id"],
            "title": row["answers_title"],
        } if row["answers_document_id"] else None
        items.append(payload)
    return {"items": items, "total": len(items)}


def _careerops_state_for_stage(stage: str) -> str:
    mapping = {
        "Discovered": "Evaluated",
        "Reviewing": "Evaluated",
        "Saved": "Evaluated",
        "Prepping": "Evaluated",
        "ReadyToApply": "Evaluated",
        "Applied": "Applied",
        "Screening": "Responded",
        "Responded": "Responded",
        "Interview": "Interview",
        "Offer": "Offer",
        "Accepted": "Hired",
        "Rejected": "Rejected",
        "Ghosted": "Rejected",
        "Skipped": "SKIP",
        "Excluded": "SKIP",
        "Declined": "Discarded",
        "Withdrawn": "Discarded",
        "Archived": "Discarded",
    }
    if stage not in mapping:
        raise ValueError(stage)
    return mapping[stage]


def _parse_window_to_seconds(window: str | None, default_days: int = 14) -> int:
    raw = (window or f"{default_days}d").strip().lower()
    if raw.endswith("d"):
        return max(1, int(raw[:-1] or default_days)) * 86400
    if raw.endswith("h"):
        return max(1, int(raw[:-1] or 24)) * 3600
    return default_days * 86400


def _upsert_document(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    kind: str,
    payload: dict[str, Any],
    now: str,
) -> str:
    existing = conn.execute(
        "SELECT id FROM documents WHERE job_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1",
        (job_id, kind),
    ).fetchone()
    doc_id = str(existing["id"]) if existing is not None else new_id()
    title = str(payload.get("title") or f"{kind.replace('_', ' ').title()} for {job_id}")
    version_label = str(payload.get("version_label") or f"{job_id}-{kind}")
    file_path = str(payload.get("path") or payload.get("file_path") or "")
    mime_type = str(payload.get("mime_type") or "application/octet-stream")
    content_text = payload.get("content_text")
    if existing is None:
        conn.execute(
            "INSERT INTO documents (id, kind, job_id, version_label, title, content_text, file_path, mime_type, generated_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, kind, job_id, version_label, title, content_text, file_path, mime_type, "jobradar.prepare", now, now),
        )
    else:
        conn.execute(
            "UPDATE documents SET version_label = ?, title = ?, content_text = ?, file_path = ?, mime_type = ?, generated_by = ?, updated_at = ? WHERE id = ?",
            (version_label, title, content_text, file_path, mime_type, "jobradar.prepare", now, doc_id),
        )
    return doc_id


def get_pipeline(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            """
            SELECT jobs.id, jobs.title_raw, jobs.status, jobs.personal_score, jobs.tier, jobs.liveness_status,
                   companies.name_raw AS company_name
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            ORDER BY jobs.personal_score DESC, jobs.discovered_at DESC
            """
        ).fetchall()
    columns = {stage: [] for stage in PIPELINE_STAGES}
    for row in rows:
        stage = row["status"] if row["status"] in columns else "Discovered"
        columns[stage].append(
            {
                "id": row["id"],
                "title": row["title_raw"],
                "company": row["company_name"],
                "status": stage,
                "personal_score": row["personal_score"],
                "tier": row["tier"],
                "liveness_status": row["liveness_status"],
            }
        )
    return {"columns": columns, "stage_order": PIPELINE_STAGES}


def move_pipeline_job(job_id: str, to_stage: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    if to_stage not in PIPELINE_STAGES:
        raise ValueError(to_stage)
    with connect(settings) as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        from_stage = row["status"]
        if from_stage != to_stage:
            conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (to_stage, now_iso(), job_id))
            ts = now_iso()
            conn.execute(
                "INSERT INTO application_events (id, job_id, event_type, from_value, to_value, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), job_id, "stage.changed", from_stage, to_stage, "human", _json_dumps({"source": "pipeline"}), ts, ts),
            )
            conn.commit()
    return {"ok": True, "job_id": job_id, "from_stage": from_stage, "to_stage": to_stage}


def get_evaluation_queue(limit: int = 8, count_only: bool = False, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            """
            SELECT
              jobs.*,
              companies.name_raw AS company_name,
              companies.domain AS domain,
              companies.logo_url AS logo_url,
              COUNT(job_sources.id) AS sources_count
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            LEFT JOIN job_sources ON job_sources.job_id = jobs.id
            WHERE jobs.is_archived = 0
              AND jobs.career_ops_report_number IS NULL
              AND jobs.tier IN ('A', 'B')
            GROUP BY jobs.id
            ORDER BY jobs.personal_score DESC, jobs.discovered_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
    if count_only:
        return {"count": len(rows)}
    return {"count": len(rows), "items": [_serialize_job_list_item(row) for row in rows]}


def attach_evaluation(
    job_id: str,
    report_number: int,
    career_ops_score: float | None = None,
    legitimacy: str | None = None,
    actor: str = "hermes",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    if (career_ops_score is None or legitimacy is None) and settings.careerops_root and settings.node_bin:
        adapter = _build_adapter(settings)
        if adapter is not None:
            try:
                report = adapter.read_report(report_number)
            except Exception:
                report = None
            if report is not None:
                if career_ops_score is None:
                    career_ops_score = report.score
                if legitimacy is None:
                    legitimacy = report.legitimacy
    with connect(settings) as conn:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        ts = now_iso()
        conn.execute(
            "UPDATE jobs SET career_ops_report_number = ?, career_ops_score = COALESCE(?, career_ops_score), career_ops_legitimacy = COALESCE(?, career_ops_legitimacy), updated_at = ? WHERE id = ?",
            (report_number, career_ops_score, legitimacy, ts, job_id),
        )
        conn.execute(
            "INSERT INTO application_events (id, job_id, event_type, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id(), job_id, "job.evaluated", actor, _json_dumps({"report_number": report_number, "career_ops_score": career_ops_score, "legitimacy": legitimacy}), ts, ts),
        )
        conn.commit()
    return {"ok": True, "job_id": job_id, "report_number": report_number}


def get_followups_due(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            """
            SELECT applications.job_id, applications.stage, applications.follow_up_at, applications.next_action,
                   applications.id AS application_id,
                   jobs.title_raw, jobs.personal_score, jobs.application_url,
                   companies.name_raw AS company_name
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            JOIN companies ON companies.id = jobs.company_id
            WHERE applications.follow_up_at IS NOT NULL
            ORDER BY applications.follow_up_at ASC
            """
        ).fetchall()
    now = datetime.now(timezone.utc)
    window_s = _parse_window_to_seconds(None)
    items = [
        {
            "application_id": row["application_id"],
            "job_id": row["job_id"],
            "company": row["company_name"],
            "title": row["title_raw"],
            "stage": row["stage"],
            "follow_up_at": row["follow_up_at"],
            "next_action": row["next_action"],
            "personal_score": row["personal_score"],
            "application_url": row["application_url"],
            "due_state": "upcoming",
        }
        for row in rows
    ]
    return {"total": len(items), "items": items}


def _get_or_create_application_for_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    stage: str,
    careerops_state: str,
    tracker_num: int | None,
    now: str,
) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        application_id = new_id()
        conn.execute(
            "INSERT INTO applications (id, job_id, stage, careerops_tracker_num, careerops_state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (application_id, job_id, stage, tracker_num, careerops_state, now, now),
        )
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return row


def prepare_job_application(job_id: str, payload: dict[str, Any], actor: str = "hermes", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    now = now_iso()
    with connect(settings) as conn:
        job = conn.execute("SELECT id, company_id, status, title_raw, application_url FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise KeyError(job_id)
        tracker_num: int | None = None
        if settings.careerops_root and settings.node_bin:
            adapter = _build_adapter(settings)
            if adapter is not None:
                reserved = adapter.reserve_report_numbers(1)
                tracker_num = reserved.start
                company_slug = _slugify(str(conn.execute("SELECT name_raw FROM companies WHERE id = ?", (job["company_id"],)).fetchone()[0]))
                adapter.add_tracker_row(
                    _build_tracker_addition(
                        report_number=tracker_num,
                        company=company_slug,
                        role=str(job["title_raw"]),
                        date=now[:10],
                        via="jobradar",
                        status="Evaluated",
                        report=f"{tracker_num:03d}",
                        notes=str(payload.get("notes") or "prepared in jobradar"),
                    )
                )
        app = _get_or_create_application_for_job(
            conn,
            job_id=job_id,
            stage="ReadyToApply",
            careerops_state=_careerops_state_for_stage("ReadyToApply"),
            tracker_num=tracker_num,
            now=now,
        )
        resume_id = None
        cover_id = None
        answers_id = None
        resume_variant_id = payload.get("resume_variant_id")
        if resume_variant_id:
            variant = conn.execute("SELECT * FROM resume_variants WHERE id = ? AND job_id = ?", (resume_variant_id, job_id)).fetchone()
            if variant is None:
                raise KeyError(resume_variant_id)
            conn.execute("UPDATE resume_variants SET is_locked = 1, updated_at = ? WHERE id = ?", (now, resume_variant_id))
            if variant["pdf_document_id"]:
                resume_id = variant["pdf_document_id"]
        if isinstance(payload.get("resume_document"), dict):
            resume_id = _upsert_document(conn, job_id=job_id, kind="resume", payload=payload["resume_document"], now=now)
        if isinstance(payload.get("cover_letter_document"), dict):
            cover_id = _upsert_document(conn, job_id=job_id, kind="cover_letter", payload=payload["cover_letter_document"], now=now)
        if isinstance(payload.get("answers_document"), dict):
            answers_id = _upsert_document(conn, job_id=job_id, kind="screening_answers", payload=payload["answers_document"], now=now)
        previous_stage = app["stage"]
        conn.execute(
            "UPDATE applications SET stage = ?, resume_document_id = COALESCE(?, resume_document_id), resume_variant_id = COALESCE(?, resume_variant_id), cover_letter_document_id = COALESCE(?, cover_letter_document_id), answers_document_id = COALESCE(?, answers_document_id), careerops_tracker_num = COALESCE(?, careerops_tracker_num), careerops_state = ?, next_action = ?, notes = ?, updated_at = ? WHERE id = ?",
            (
                "ReadyToApply",
                resume_id,
                resume_variant_id,
                cover_id,
                answers_id,
                tracker_num,
                _careerops_state_for_stage("ReadyToApply"),
                payload.get("next_action"),
                payload.get("notes"),
                now,
                app["id"],
            ),
        )
        conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", ("ReadyToApply", now, job_id))
        conn.execute(
            "INSERT INTO application_events (id, application_id, job_id, event_type, from_value, to_value, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), app["id"], job_id, "stage.changed", previous_stage, "ReadyToApply", actor, _json_dumps({"source": "prepare"}), now, now),
        )
        conn.execute(
            "INSERT INTO application_events (id, application_id, job_id, event_type, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), app["id"], job_id, "application.prepared", actor, _json_dumps({"tracker_num": tracker_num, "resume_variant_id": resume_variant_id}), now, now),
        )
        conn.commit()
    return {"ok": True, "job_id": job_id, "application_id": app["id"], "stage": "ReadyToApply", "task_id": f"prepare-{job_id}"}


def mark_job_applied(job_id: str, payload: dict[str, Any], actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    now = now_iso()
    tracker_num: int | None = None
    with connect(settings) as conn:
        app = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        if app is None:
            app = _get_or_create_application_for_job(conn, job_id=job_id, stage="Applied", careerops_state=_careerops_state_for_stage("Applied"), tracker_num=None, now=now)
        tracker_num = app["careerops_tracker_num"]
        resume_variant_id = payload.get("resume_variant_id") or app["resume_variant_id"]
        if resume_variant_id:
            variant = conn.execute("SELECT * FROM resume_variants WHERE id = ? AND job_id = ?", (resume_variant_id, job_id)).fetchone()
            if variant is None:
                raise KeyError(resume_variant_id)
            conn.execute("UPDATE resume_variants SET is_locked = 1, updated_at = ? WHERE id = ?", (now, resume_variant_id))
        conn.execute(
            "UPDATE applications SET stage = 'Applied', applied_at = ?, applied_via = ?, follow_up_at = ?, notes = ?, careerops_state = ?, resume_variant_id = COALESCE(?, resume_variant_id), updated_at = ? WHERE id = ?",
            (now, payload.get("applied_via"), payload.get("follow_up_at"), payload.get("notes"), _careerops_state_for_stage("Applied"), resume_variant_id, now, app["id"]),
        )
        conn.execute("UPDATE jobs SET status = 'Applied', updated_at = ? WHERE id = ?", (now, job_id))
        conn.execute(
            "INSERT INTO application_events (id, application_id, job_id, event_type, from_value, to_value, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), app["id"], job_id, "application.applied", app["stage"], "Applied", actor, _json_dumps({**payload, "resume_variant_id": resume_variant_id}), now, now),
        )
        conn.commit()
    if settings.careerops_root and settings.node_bin and tracker_num:
        adapter = _build_adapter(settings)
        if adapter is not None:
            adapter.set_status(str(tracker_num), "Applied", note=str(payload.get("notes") or "applied in jobradar"))
            adapter.sync_tracker_index()
    return {"ok": True, "job_id": job_id, "application_id": app["id"], "stage": "Applied"}


def update_job_application_status(job_id: str, stage: str, note: str | None = None, follow_up_at: str | None = None, actor: str = "hermes", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    now = now_iso()
    tracker_num: int | None = None
    with connect(settings) as conn:
        app = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        if app is None:
            raise KeyError(job_id)
        tracker_num = app["careerops_tracker_num"]
        careerops_state = _careerops_state_for_stage(stage)
        response_at = now if stage in {"Responded", "Screening", "Interview", "Offer"} else app["response_at"]
        conn.execute(
            "UPDATE applications SET stage = ?, careerops_state = ?, follow_up_at = COALESCE(?, follow_up_at), response_at = ?, notes = COALESCE(?, notes), updated_at = ? WHERE id = ?",
            (stage, careerops_state, follow_up_at, response_at, note, now, app["id"]),
        )
        conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (stage, now, job_id))
        conn.execute(
            "INSERT INTO application_events (id, application_id, job_id, event_type, from_value, to_value, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), app["id"], job_id, "application.status_changed", app["stage"], stage, actor, _json_dumps({"note": note, "follow_up_at": follow_up_at}), now, now),
        )
        conn.commit()
    if settings.careerops_root and settings.node_bin and tracker_num:
        adapter = _build_adapter(settings)
        if adapter is not None:
            adapter.set_status(str(tracker_num), careerops_state, note=note or f"status -> {stage}")
    return {"ok": True, "job_id": job_id, "application_id": app["id"], "stage": stage}


def complete_followup(application_id: str, payload: dict[str, Any], actor: str = "hermes", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    now = now_iso()
    with connect(settings) as conn:
        app = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if app is None:
            raise KeyError(application_id)
        conn.execute(
            "UPDATE applications SET last_contact_at = ?, follow_up_at = ?, notes = COALESCE(?, notes), updated_at = ? WHERE id = ?",
            (payload.get("contact_at"), payload.get("next_follow_up_at"), payload.get("note"), now, application_id),
        )
        conn.execute(
            "INSERT INTO application_events (id, application_id, job_id, event_type, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), application_id, app["job_id"], "followup.completed", actor, _json_dumps(payload), now, now),
        )
        conn.commit()
    return {"ok": True, "application_id": application_id}


def refresh_liveness(job_ids: list[str] | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            rows = conn.execute(
                f"SELECT id, status FROM jobs WHERE id IN ({placeholders})",
                tuple(job_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, status FROM jobs WHERE is_archived = 0 AND status IN ('Discovered', 'Reviewing', 'Saved', 'Prepping', 'Applied', 'Screening', 'Interview', 'Offer')"
            ).fetchall()
        ts = now_iso()
        changed = 0
        for row in rows:
            new_status = "Active" if row["status"] in {"Applied", "Screening", "Interview", "Offer"} else "Fresh"
            conn.execute("UPDATE jobs SET liveness_status = ?, last_verified_at = ?, updated_at = ? WHERE id = ?", (new_status, ts, ts, row["id"]))
            changed += 1
        conn.commit()
    return {"ok": True, "checked": len(rows), "updated": changed}


def get_analytics(window: str = "90d", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)

    def pct(num: int, den: int) -> float:
        return round((num / den) * 100, 1) if den else 0.0

    stage_order = ["Applied", "Responded", "Screening", "Interview", "Offer", "Hired", "Rejected", "Withdrawn"]
    with connect(settings) as conn:
        applications_sent = int(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0])
        total_jobs = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE is_archived = 0").fetchone()[0])
        by_status_rows = conn.execute("SELECT status, COUNT(*) AS count FROM jobs WHERE is_archived = 0 GROUP BY status").fetchall()
        app_stage_rows = conn.execute("SELECT stage, COUNT(*) AS count FROM applications GROUP BY stage").fetchall()
        responded = int(conn.execute("SELECT COUNT(*) FROM applications WHERE stage IN ('Responded','Screening','Interview','Offer','Hired') OR response_at IS NOT NULL").fetchone()[0])
        interviews = int(conn.execute("SELECT COUNT(*) FROM applications WHERE stage IN ('Interview','Offer','Hired')").fetchone()[0])
        offers = int(conn.execute("SELECT COUNT(*) FROM applications WHERE stage IN ('Offer','Hired') OR offer_at IS NOT NULL").fetchone()[0])
        followup_total = int(conn.execute("SELECT COUNT(*) FROM applications WHERE follow_up_at IS NOT NULL").fetchone()[0])
        followup_completed = int(conn.execute("SELECT COUNT(*) FROM applications WHERE follow_up_at IS NOT NULL AND last_contact_at IS NOT NULL").fetchone()[0])
        followup_due_open = int(conn.execute("SELECT COUNT(*) FROM applications WHERE follow_up_at IS NOT NULL AND COALESCE(last_contact_at, '') = '' AND follow_up_at <= ?", (now_iso(),)).fetchone()[0])
        resume_rows = conn.execute(
            """
            SELECT
              COALESCE(rv.version_label, d.version_label, 'no_resume_variant') AS version_label,
              COALESCE(rv.id, a.resume_variant_id, '') AS resume_variant_id,
              COUNT(*) AS applications,
              SUM(CASE WHEN a.stage IN ('Responded','Screening','Interview','Offer','Hired') OR a.response_at IS NOT NULL THEN 1 ELSE 0 END) AS responses,
              SUM(CASE WHEN a.stage IN ('Interview','Offer','Hired') THEN 1 ELSE 0 END) AS interviews,
              SUM(CASE WHEN a.stage IN ('Offer','Hired') OR a.offer_at IS NOT NULL THEN 1 ELSE 0 END) AS offers
            FROM applications a
            LEFT JOIN resume_variants rv ON rv.id = a.resume_variant_id
            LEFT JOIN documents d ON d.id = a.resume_document_id
            GROUP BY COALESCE(rv.version_label, d.version_label, 'no_resume_variant'), COALESCE(rv.id, a.resume_variant_id, '')
            ORDER BY applications DESC, responses DESC
            LIMIT 10
            """
        ).fetchall()
        top_rows = conn.execute(
            """
            SELECT jobs.id, jobs.title_raw, jobs.personal_score, jobs.status, companies.name_raw AS company_name
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.is_archived = 0
            ORDER BY jobs.personal_score DESC, jobs.discovered_at DESC
            LIMIT 5
            """
        ).fetchall()
    by_status = {row["status"]: row["count"] for row in by_status_rows}
    by_stage = {stage: 0 for stage in stage_order}
    for row in app_stage_rows:
        by_stage[row["stage"]] = int(row["count"])
    small_sample = applications_sent < 10
    warnings = []
    if small_sample:
        warnings.append("Application sample is below 10; conversion rates are directional, not statistically reliable.")
    if followup_due_open:
        warnings.append(f"{followup_due_open} follow-up(s) are due and not marked contacted.")
    return {
        "window": window,
        "applications_sent": applications_sent,
        "jobs_total": total_jobs,
        "by_status": by_status,
        "by_stage": by_stage,
        "funnel": {
            "applied": applications_sent,
            "responded": responded,
            "interview": interviews,
            "offer": offers,
            "response_rate": pct(responded, applications_sent),
            "interview_rate": pct(interviews, applications_sent),
            "offer_rate": pct(offers, applications_sent),
            "small_sample": small_sample,
        },
        "followup_compliance": {
            "tracked": followup_total,
            "completed": followup_completed,
            "due_open": followup_due_open,
            "completion_rate": pct(followup_completed, followup_total),
        },
        "resume_attribution": [
            {
                "resume_variant_id": row["resume_variant_id"] or None,
                "version_label": row["version_label"],
                "applications": int(row["applications"] or 0),
                "responses": int(row["responses"] or 0),
                "interviews": int(row["interviews"] or 0),
                "offers": int(row["offers"] or 0),
                "response_rate": pct(int(row["responses"] or 0), int(row["applications"] or 0)),
            }
            for row in resume_rows
        ],
        "warnings": warnings,
        "top_jobs": [
            {
                "id": row["id"],
                "company": row["company_name"],
                "title": row["title_raw"],
                "personal_score": row["personal_score"],
                "status": row["status"],
            }
            for row in top_rows
        ],
    }


def get_digest(since: str = "24h", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    jobs = list_jobs(settings)["items"]
    followups = get_followups_due(settings)
    latest_scan = get_latest_scan(settings)
    return {
        "since": since,
        "new_jobs_count": len(jobs),
        "top_jobs": jobs[:5],
        "followups_due_count": followups["total"],
        "followups": followups["items"][:10],
        "latest_scan": latest_scan,
    }


def get_health(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        jobs = int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        scans = int(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0])
        h1b_count = int(conn.execute("SELECT COUNT(*) FROM h1b_employer_stats").fetchone()[0])
        lca_count = int(conn.execute("SELECT COUNT(*) FROM lca_records").fetchone()[0])
        h1b_loaded_at = conn.execute("SELECT MAX(loaded_at) FROM h1b_employer_stats").fetchone()[0]
        lca_loaded_at = conn.execute("SELECT MAX(loaded_at) FROM lca_records").fetchone()[0]
        fiscal_year_rows = conn.execute(
            """
            SELECT fiscal_year FROM h1b_employer_stats
            UNION
            SELECT fiscal_year FROM lca_records
            ORDER BY fiscal_year DESC
            """
        ).fetchall()
    db_status = "ok" if integrity == "ok" else "error"
    dataset_status = "ok" if h1b_count or lca_count else "missing"
    overall = "ok" if db_status == "ok" else "error"
    careerops = _read_careerops_snapshot(settings)
    scheduler = _read_scheduler_snapshot(settings)
    if careerops["status"] == "error" or scheduler["status"] == "error":
        overall = "degraded" if overall == "ok" else overall
    elif careerops["status"] == "degraded" or scheduler["status"] == "degraded":
        overall = "degraded" if overall == "ok" else overall
    return {
        "status": overall,
        "checks": {
            "app": {"status": "ok", "version": "phase6-dev", "uptime_s": 0},
            "database": {"status": db_status, "journal_mode": journal_mode, "jobs": jobs, "scans": scans},
            "careerops": careerops,
            "scheduler": scheduler,
            "datasets": {
                "status": dataset_status,
                "h1b_rows": h1b_count,
                "lca_rows": lca_count,
                "h1b_loaded_at": h1b_loaded_at,
                "lca_loaded_at": lca_loaded_at,
                "fiscal_years": [int(row["fiscal_year"]) for row in fiscal_year_rows],
            },
            "disk": {"status": "ok", "free_gb": None},
        },
    }


def get_readiness(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.execute("SELECT 1")
    careerops = _read_careerops_snapshot(settings)
    return {
        "ok": integrity == "ok",
        "database": "ok" if integrity == "ok" else "error",
        "adapter": careerops["status"],
        "bind_host": settings.bind_host,
        "bind_port": settings.bind_port,
    }


def list_automation_runs(limit: int = 20, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT id, kind, name, scan_id, job_id, argv, exit_code, duration_ms, stdout_head, stderr_head, status, started_at, finished_at, created_at FROM automation_runs ORDER BY started_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


def list_automation_failures(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT id, scan_id, stage, error, raw_payload, resolved, created_at FROM ingest_failures WHERE resolved = 0 ORDER BY created_at DESC"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


def retry_ingest_failure(failure_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        failure = conn.execute(
            "SELECT id, scan_id, stage, error, raw_payload, resolved, created_at FROM ingest_failures WHERE id = ?",
            (failure_id,),
        ).fetchone()
        if failure is None:
            raise KeyError(failure_id)
        ts = now_iso()
        conn.execute("UPDATE ingest_failures SET resolved = 1 WHERE id = ?", (failure_id,))
        conn.execute(
            "INSERT INTO automation_runs (id, kind, name, scan_id, argv, exit_code, duration_ms, stdout_head, stderr_head, status, started_at, finished_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id(),
                "ingest_retry",
                "retry_failure",
                failure["scan_id"],
                _json_dumps(["retry", failure_id]),
                0,
                0,
                "resolved without requeue",
                "",
                "completed",
                ts,
                ts,
                ts,
            ),
        )
        conn.commit()
    return {"ok": True, "failure_id": failure_id, "resolved": True}


def get_automation_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    latest_scan = get_latest_scan(settings)
    with connect(settings) as conn:
        run_counts_rows = conn.execute("SELECT status, COUNT(*) AS count FROM automation_runs GROUP BY status").fetchall()
        unresolved = int(conn.execute("SELECT COUNT(*) FROM ingest_failures WHERE resolved = 0").fetchone()[0])
        resolved = int(conn.execute("SELECT COUNT(*) FROM ingest_failures WHERE resolved = 1").fetchone()[0])
    run_counts = {row["status"]: row["count"] for row in run_counts_rows}
    return {
        "latest_scan": latest_scan,
        "health": get_health(settings),
        "run_counts": run_counts,
        "failure_counts": {"unresolved": unresolved, "resolved": resolved},
    }


def create_scan(mode: str, trigger: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    scan_id = new_id()
    ts = now_iso()
    with connect(settings) as conn:
        stale_after = max(60, int(settings.running_scan_stale_after_s))
        running_rows = conn.execute("SELECT id, started_at, warnings FROM scans WHERE status = 'running' ORDER BY started_at DESC").fetchall()
        active_running: str | None = None
        for row in running_rows:
            started_at = str(row["started_at"] or "")
            age_s: int | None = None
            try:
                age_s = int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())
            except Exception:
                age_s = None
            if age_s is not None and age_s > stale_after:
                warnings = str(row["warnings"] or "")
                stale_note = f"stale running scan auto-failed after {age_s}s"
                combined = stale_note if not warnings else f"{warnings}; {stale_note}"
                conn.execute(
                    "UPDATE scans SET status = 'failed', finished_at = ?, warnings = ? WHERE id = ?",
                    (ts, combined, row["id"]),
                )
            else:
                active_running = str(row["id"])
                break
        if active_running is not None:
            raise RuntimeError(active_running)
        conn.execute(
            "INSERT INTO scans (id, mode, trigger, status, started_at, created_at) VALUES (?, ?, ?, 'running', ?, ?)",
            (scan_id, mode, trigger, ts, ts),
        )
        conn.commit()
    return scan_id


def ingest_scan(scan_id: str, candidates_payload: list[dict[str, Any]], settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    jobs_added = 0
    jobs_updated = 0
    jobs_excluded = 0
    duplicates_merged = 0
    failures = 0
    now = now_iso()
    normalized_records: list[tuple[dict[str, Any], Any]] = []
    with connect(settings) as conn:
        scan = conn.execute("SELECT id FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if scan is None:
            raise KeyError(scan_id)
        for raw in candidates_payload:
            try:
                required = [raw.get("source_platform"), raw.get("source_url"), raw.get("company"), raw.get("title")]
                if any(not value for value in required):
                    raise ValueError("missing required field")
                candidate = CandidateRecord(
                    source_platform=str(raw["source_platform"]),
                    source_url=str(raw["source_url"]),
                    company=str(raw["company"]),
                    title=str(raw["title"]),
                    location=str(raw.get("location") or ""),
                    description_html=str(raw.get("description_html") or ""),
                    description_text=str(raw.get("description_text") or ""),
                    application_url=raw.get("application_url"),
                    salary_text=raw.get("salary_text"),
                )
                normalized = apply_exclusions(normalize_candidate(candidate))
                normalized_records.append((raw, normalized))
            except Exception as exc:
                failures += 1
                _insert_scan_source(
                    conn,
                    scan_id=scan_id,
                    source_platform=str(raw.get("source_platform") or "unknown"),
                    source_url=str(raw.get("source_url") or ""),
                    status="failed",
                    jobs_found=0,
                    jobs_new=0,
                    error=str(exc),
                    created_at=now,
                )
                conn.execute(
                    "INSERT INTO ingest_failures (id, scan_id, stage, error, raw_payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id(), scan_id, "normalize", str(exc), json.dumps(raw, sort_keys=True), now),
                )
        deduped = dedupe_candidates([item[1] for item in normalized_records])
        deduped_by_key = {item.canonical_url or item.application_url: item for item in deduped}
        seen_new_keys: set[str] = set()
        for raw, normalized in normalized_records:
            deduped_key = normalized.canonical_url or normalized.application_url
            merged = deduped_by_key[deduped_key]
            dedupe_key = merged.canonical_url or merged.application_url
            existing = conn.execute("SELECT id, duplicate_count FROM jobs WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            if existing is None and deduped_key in seen_new_keys:
                existing = conn.execute("SELECT id, duplicate_count FROM jobs WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            if merged.status == "Excluded":
                jobs_excluded += 1
            company_id = _company_lookup_or_create(conn, merged.company_name_raw, now)
            if existing is None:
                seen_new_keys.add(deduped_key)
                job_id = new_id()
                sponsorship_class, sponsorship_confidence, evidence = _classify_sponsorship(
                    conn,
                    company_name_normalized=normalized.company_name_normalized,
                    description_text=normalized.description_text,
                    exclusion_reason=normalized.exclusion_reason,
                    created_at=now,
                )
                personal_score, tier, score_breakdown, fit_reasons, concerns = _compute_personal_score(
                    title_raw=normalized.title_raw,
                    title_normalized=normalized.title_normalized,
                    description_text=normalized.description_text,
                    work_mode=normalized.work_mode,
                    remote_scope=normalized.remote_scope,
                    sponsorship_class=sponsorship_class,
                    exclusion_reason=normalized.exclusion_reason,
                )
                conn.execute(
                    """
                    INSERT INTO jobs (
                      id, dedupe_key, company_id, canonical_url, application_url, source_url,
                      canonical_confidence, source_platform, discovery_method, title_raw,
                      title_normalized, location_raw, work_mode, remote_scope,
                      discovered_at, first_seen_scan_id, description_text, description_html_sanitized,
                      description_sha256, description_simhash, status, exclusion_reason,
                      injection_flag, injection_detail, parse_confidence, duplicate_count,
                      sponsorship_class, sponsorship_confidence, sponsorship_computed_at, sponsorship_rule_version,
                      personal_score, score_version, score_breakdown, fit_reasons, concerns, tier, liveness_status,
                      sponsorship_evidence_id,
                      created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scan', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id, dedupe_key, company_id, normalized.canonical_url, normalized.application_url, normalized.source_url,
                        normalized.canonical_confidence, normalized.source_platform, normalized.title_raw,
                        normalized.title_normalized, normalized.location_raw, normalized.work_mode, normalized.remote_scope,
                        now, scan_id, normalized.description_text, normalized.description_html_sanitized,
                        normalized.description_sha256, normalized.description_simhash, normalized.status, normalized.exclusion_reason,
                        1 if "ignore previous instructions" in normalized.description_text.casefold() else 0,
                        "detected" if "ignore previous instructions" in normalized.description_text.casefold() else "",
                        "full", 1,
                        sponsorship_class, sponsorship_confidence, now, 1,
                        personal_score, 1, score_breakdown, fit_reasons, concerns, tier, "New",
                        None,
                        now, now,
                    ),
                )
                conn.execute(
                    "INSERT INTO job_snapshots (id, job_id, captured_at, capture_reason, content_text, content_html_sanitized, content_sha256, created_at) VALUES (?, ?, ?, 'discovery', ?, ?, ?, ?)",
                    (new_id(), job_id, now, normalized.description_text, normalized.description_html_sanitized, normalized.description_sha256, now),
                )
                evidence_id = _persist_sponsorship_evidence(
                    conn,
                    job_id=job_id,
                    company_id=company_id,
                    evidence=evidence,
                    created_at=now,
                )
                conn.execute("UPDATE jobs SET sponsorship_evidence_id = ? WHERE id = ?", (evidence_id, job_id))
                _insert_scan_source(
                    conn,
                    scan_id=scan_id,
                    source_platform=normalized.source_platform,
                    source_url=normalized.source_url,
                    status="ok",
                    jobs_found=1,
                    jobs_new=1,
                    error=None,
                    created_at=now,
                )
                _record_event(conn, job_id=job_id, event_type="job.discovered", actor="system", detail={"scan_id": scan_id})
                jobs_added += 1
            else:
                job_id = str(existing[0])
                current = conn.execute("SELECT description_text, duplicate_count FROM jobs WHERE id = ?", (job_id,)).fetchone()
                updates: dict[str, Any] = {
                    "duplicate_count": max(int(current["duplicate_count"]), merged.duplicate_count),
                    "updated_at": now,
                }
                changed_fields: list[str] = []
                if len(merged.description_text) > len(current["description_text"] or ""):
                    updates.update({
                        "description_text": merged.description_text,
                        "description_html_sanitized": merged.description_html_sanitized,
                        "description_sha256": merged.description_sha256,
                        "description_simhash": merged.description_simhash,
                    })
                    changed_fields.append("description_text")
                if updates.get("duplicate_count") != current["duplicate_count"]:
                    changed_fields.append("duplicate_count")
                if changed_fields:
                    conn.execute(
                        "UPDATE jobs SET description_text = COALESCE(?, description_text), description_html_sanitized = COALESCE(?, description_html_sanitized), description_sha256 = COALESCE(?, description_sha256), description_simhash = COALESCE(?, description_simhash), duplicate_count = ?, updated_at = ? WHERE id = ?",
                        (
                            updates.get("description_text"), updates.get("description_html_sanitized"), updates.get("description_sha256"), updates.get("description_simhash"), updates["duplicate_count"], updates["updated_at"], job_id,
                        ),
                    )
                    jobs_updated += 1
                    duplicates_merged += 1
                    _record_event(conn, job_id=job_id, event_type="job.merged", actor="system", detail={"scan_id": scan_id, "fields": changed_fields})
                _insert_scan_source(
                    conn,
                    scan_id=scan_id,
                    source_platform=normalized.source_platform,
                    source_url=normalized.source_url,
                    status="ok",
                    jobs_found=1,
                    jobs_new=0,
                    error=None,
                    created_at=now,
                )
            source_exists = conn.execute(
                "SELECT 1 FROM job_sources WHERE job_id = ? AND source_platform = ? AND source_url = ?",
                (job_id, normalized.source_platform, normalized.source_url),
            ).fetchone()
            if source_exists is None:
                conn.execute(
                    "INSERT INTO job_sources (id, job_id, source_platform, source_url, discovered_at, scan_id, raw_payload_sha256, raw_payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id(), job_id, normalized.source_platform, normalized.source_url, now, scan_id, normalized.description_sha256, json.dumps(raw, sort_keys=True), now),
                )
        status = "completed"
        if failures and (jobs_added or jobs_updated):
            status = "partial"
        elif failures and not (jobs_added or jobs_updated):
            status = "failed"
        conn.execute(
            "UPDATE scans SET status = ?, finished_at = ?, jobs_added = ?, jobs_updated = ?, duplicates_merged = ?, jobs_excluded = ?, jobs_seen = ?, sources_attempted = ?, sources_succeeded = ?, sources_failed = ? WHERE id = ?",
            (
                status, now, jobs_added, jobs_updated, duplicates_merged, jobs_excluded,
                len(candidates_payload), len(candidates_payload), len(candidates_payload) - failures, failures, scan_id,
            ),
        )
        rebuild_fts(conn)
        conn.commit()
    return {
        "jobs_added": jobs_added,
        "jobs_updated": jobs_updated,
        "duplicates_merged": duplicates_merged,
        "jobs_excluded": jobs_excluded,
        "failures": failures,
        "evaluation_queue_depth": 0,
    }


def import_legacy_processed(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    companies_added = 0
    jobs_added = 0
    with connect(settings) as conn:
        for path in sorted(settings.import_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = payload.get("record", {})
            structured = payload.get("structured", {})
            company_name = (record.get("company") or structured.get("company") or "Unknown").strip()
            title = (record.get("title") or structured.get("title") or "Unknown").strip()
            source_url = (record.get("link") or structured.get("link") or "").strip()
            source_platform = (record.get("source") or structured.get("source") or "unknown").strip() or "unknown"
            dedupe_key = (record.get("jobId") or source_url or f"{company_name}:{title}").strip().lower()
            company_norm = company_name.lower()
            company = conn.execute("SELECT id FROM companies WHERE name_normalized = ?", (company_norm,)).fetchone()
            if company is None:
                company_id = new_id()
                ts = now_iso()
                conn.execute("INSERT INTO companies (id, name_raw, name_normalized, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (company_id, company_name, company_norm, ts, ts))
                companies_added += 1
            else:
                company_id = company["id"]
            existing = conn.execute("SELECT id FROM jobs WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            if existing is not None:
                continue
            job_id = new_id()
            ts = now_iso()
            conn.execute(
                """
                INSERT INTO jobs (
                  id, dedupe_key, company_id, title_raw, title_normalized, location_raw,
                  source_platform, source_url, application_url, description_text,
                  personal_score, sponsorship_class, status, discovered_at, created_at,
                  updated_at, discovery_method, canonical_confidence, parse_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, dedupe_key, company_id, title, title.lower(), (record.get("location") or structured.get("location") or "").strip(),
                    source_platform, source_url, source_url, structured.get("description") or "", record.get("score"),
                    record.get("sponsorshipStatus") or "unknown", "Discovered", record.get("reviewedAt") or ts, ts, ts, "import", "low", "partial",
                ),
            )
            conn.execute(
                "INSERT INTO job_sources (id, job_id, source_platform, source_url, discovered_at, raw_payload_sha256, raw_payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), job_id, source_platform, source_url, ts, None, json.dumps(payload), ts),
            )
            conn.execute(
                "INSERT INTO application_events (id, job_id, event_type, actor, detail, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_id(), job_id, "job.imported", "system", json.dumps({"source_file": path.name}), ts, ts),
            )
            jobs_added += 1
        rebuild_fts(conn)
        conn.commit()
    return {"companies_added": companies_added, "jobs_added": jobs_added}


def _bool_to_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _normalize_company_name(name: str) -> str:
    return " ".join((name or "").casefold().split())


def _serialize_company(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name_raw"],
        "name_normalized": row["name_normalized"],
        "domain": row["domain"],
        "logo_url": row["logo_url"],
        "industry": row["industry"],
        "size_band": row["size_band"],
        "hq_city": row["hq_city"],
        "hq_state": row["hq_state"],
        "careers_url": row["careers_url"],
        "ats_platform": row["ats_platform"],
        "ats_slug": row["ats_slug"],
        "is_target": bool(row["is_target"]),
        "is_blacklisted": bool(row["is_blacklisted"]),
        "priority": row["priority"],
        "research_document_id": row["research_document_id"],
        "h1b_total_3yr": row["h1b_total_3yr"],
        "h1b_last_fy": row["h1b_last_fy"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_companies(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM companies ORDER BY priority DESC, name_raw ASC"
        ).fetchall()
    items = [_serialize_company(row) for row in rows]
    return {"items": items, "total": len(items)}


def get_company(company_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            raise KeyError(company_id)
    return _serialize_company(row)


def create_company(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name required")
    ts = now_iso()
    company_id = new_id()
    with connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO companies (
              id, name_raw, name_normalized, domain, logo_url, industry, size_band,
              hq_city, hq_state, careers_url, ats_platform, ats_slug, is_target,
              is_blacklisted, priority, research_document_id, h1b_total_3yr,
              h1b_last_fy, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                name,
                _normalize_company_name(name),
                payload.get("domain"),
                payload.get("logo_url"),
                payload.get("industry"),
                payload.get("size_band"),
                payload.get("hq_city"),
                payload.get("hq_state"),
                payload.get("careers_url"),
                payload.get("ats_platform"),
                payload.get("ats_slug"),
                _bool_to_int(payload.get("is_target")),
                _bool_to_int(payload.get("is_blacklisted")),
                int(payload.get("priority") or 0),
                payload.get("research_document_id"),
                payload.get("h1b_total_3yr"),
                payload.get("h1b_last_fy"),
                payload.get("notes"),
                ts,
                ts,
            ),
        )
        conn.commit()
    return get_company(company_id, settings)


def update_company(company_id: str, payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name required")
    with connect(settings) as conn:
        exists = conn.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone()
        if exists is None:
            raise KeyError(company_id)
        conn.execute(
            """
            UPDATE companies
            SET name_raw = ?, name_normalized = ?, domain = ?, logo_url = ?, industry = ?, size_band = ?,
                hq_city = ?, hq_state = ?, careers_url = ?, ats_platform = ?, ats_slug = ?, is_target = ?,
                is_blacklisted = ?, priority = ?, research_document_id = ?, h1b_total_3yr = ?,
                h1b_last_fy = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                _normalize_company_name(name),
                payload.get("domain"),
                payload.get("logo_url"),
                payload.get("industry"),
                payload.get("size_band"),
                payload.get("hq_city"),
                payload.get("hq_state"),
                payload.get("careers_url"),
                payload.get("ats_platform"),
                payload.get("ats_slug"),
                _bool_to_int(payload.get("is_target")),
                _bool_to_int(payload.get("is_blacklisted")),
                int(payload.get("priority") or 0),
                payload.get("research_document_id"),
                payload.get("h1b_total_3yr"),
                payload.get("h1b_last_fy"),
                payload.get("notes"),
                now_iso(),
                company_id,
            ),
        )
        conn.commit()
    return get_company(company_id, settings)


def delete_company(company_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        deleted = conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        conn.commit()
    if deleted.rowcount == 0:
        raise KeyError(company_id)
    return {"ok": True, "id": company_id}


def _serialize_document(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def list_documents(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY updated_at DESC, created_at DESC").fetchall()
    return {"items": [_serialize_document(row) for row in rows], "total": len(rows)}


def get_document(document_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
    return _serialize_document(row)


def create_document(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    kind = str(payload.get("kind") or "").strip()
    version_label = str(payload.get("version_label") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not kind or not version_label or not title:
        raise ValueError("kind, version_label, and title required")
    document_id = new_id()
    ts = now_iso()
    with connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO documents (
              id, kind, job_id, version_label, title, content_text, file_path,
              file_sha256, mime_type, generated_by, ats_keyword_coverage, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                kind,
                payload.get("job_id"),
                version_label,
                title,
                payload.get("content_text"),
                payload.get("file_path"),
                payload.get("file_sha256"),
                payload.get("mime_type"),
                payload.get("generated_by"),
                payload.get("ats_keyword_coverage"),
                ts,
                ts,
            ),
        )
        conn.commit()
    return get_document(document_id, settings)


def update_document(document_id: str, payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    kind = str(payload.get("kind") or "").strip()
    version_label = str(payload.get("version_label") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not kind or not version_label or not title:
        raise ValueError("kind, version_label, and title required")
    with connect(settings) as conn:
        exists = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if exists is None:
            raise KeyError(document_id)
        conn.execute(
            """
            UPDATE documents
            SET kind = ?, job_id = ?, version_label = ?, title = ?, content_text = ?, file_path = ?,
                file_sha256 = ?, mime_type = ?, generated_by = ?, ats_keyword_coverage = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                kind,
                payload.get("job_id"),
                version_label,
                title,
                payload.get("content_text"),
                payload.get("file_path"),
                payload.get("file_sha256"),
                payload.get("mime_type"),
                payload.get("generated_by"),
                payload.get("ats_keyword_coverage"),
                now_iso(),
                document_id,
            ),
        )
        conn.commit()
    return get_document(document_id, settings)


def delete_document(document_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        deleted = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.commit()
    if deleted.rowcount == 0:
        raise KeyError(document_id)
    return {"ok": True, "id": document_id}




_RESUME_TERM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Splunk", re.compile(r"\bsplunk\b", re.I)),
    ("Microsoft Sentinel", re.compile(r"\b(microsoft\s+sentinel|sentinel)\b", re.I)),
    ("SentinelOne", re.compile(r"\bsentinelone\b", re.I)),
    ("SIEM", re.compile(r"\bsiem\b", re.I)),
    ("SOC", re.compile(r"\bsoc\b", re.I)),
    ("Alert Triage", re.compile(r"\balert\s+triage\b", re.I)),
    ("Incident Response", re.compile(r"\bincident\s+response\b", re.I)),
    ("Threat Intelligence", re.compile(r"\bthreat\s+intel(?:ligence)?\b", re.I)),
    ("Detection Engineering", re.compile(r"\bdetection\s+engineering\b", re.I)),
    ("Wazuh", re.compile(r"\bwazuh\b", re.I)),
    ("Suricata", re.compile(r"\bsuricata\b", re.I)),
    ("osquery", re.compile(r"\bosquery\b", re.I)),
    ("Python", re.compile(r"\bpython\b", re.I)),
    ("Bash", re.compile(r"\bbash\b", re.I)),
    ("PowerShell", re.compile(r"\bpowershell\b", re.I)),
    ("Docker", re.compile(r"\bdocker\b", re.I)),
    ("OWASP", re.compile(r"\bowasp\b", re.I)),
    ("Burp Suite", re.compile(r"\bburp\s+suite\b", re.I)),
    ("Nmap", re.compile(r"\bnmap\b", re.I)),
    ("Jira", re.compile(r"\bjira\b", re.I)),
    ("HIPAA", re.compile(r"\bhipaa\b", re.I)),
    ("CIS Controls", re.compile(r"\bcis\s+controls\b", re.I)),
    ("Security+", re.compile(r"\bsecurity\+|comptia\s+security\+\b", re.I)),
]

_KNOWN_CANDIDATE_SKILLS = {label for label, _ in _RESUME_TERM_PATTERNS}

_FABRICATION_GUARD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CrowdStrike Falcon", re.compile(r"\bcrowdstrike(?:\s+falcon)?\b", re.I)),
    ("Google Chronicle", re.compile(r"\b(?:google\s+)?chronicle\b", re.I)),
    ("IBM QRadar", re.compile(r"\b(?:ibm\s+)?qradar\b", re.I)),
    ("Cortex XSOAR", re.compile(r"\b(?:cortex\s+)?xsoar\b", re.I)),
    ("Carbon Black", re.compile(r"\bcarbon\s+black\b", re.I)),
]


def _resume_terms_from_text(text: str) -> list[str]:
    found: list[str] = []
    for label, pattern in _RESUME_TERM_PATTERNS:
        if pattern.search(text or ""):
            found.append(label)
    return found


def _fabrication_guard_terms_from_text(text: str) -> list[str]:
    found: list[str] = []
    for label, pattern in _FABRICATION_GUARD_PATTERNS:
        if pattern.search(text or ""):
            found.append(label)
    return found


def _serialize_resume_base(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["content_preview"] = (payload.get("content_text") or "")[:280]
    return payload


def _resume_variant_hm_audit_document(conn: sqlite3.Connection, variant_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE kind = 'hm_audit' AND version_label = ? ORDER BY updated_at DESC, created_at DESC LIMIT 1",
        (f"{variant_id}-hm-audit",),
    ).fetchone()



def _serialize_resume_variant(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    payload = dict(row)
    if conn is not None:
        analyses = conn.execute(
            "SELECT * FROM ats_analyses WHERE resume_variant_id = ? ORDER BY created_at DESC",
            (row["id"],),
        ).fetchall()
        suggestions = conn.execute(
            "SELECT * FROM resume_suggestions WHERE resume_variant_id = ? ORDER BY created_at ASC",
            (row["id"],),
        ).fetchall()
        payload["ats_analyses"] = []
        for item in analyses:
            row_payload = dict(item)
            try:
                row_payload["detail"] = json.loads(row_payload.get("detail_json") or "{}")
            except Exception:
                row_payload["detail"] = row_payload.get("detail_json")
            payload["ats_analyses"].append(row_payload)
        payload["suggestions"] = [dict(item) for item in suggestions]
        if row["pdf_document_id"]:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (row["pdf_document_id"],)).fetchone()
            payload["document"] = _serialize_document(doc) if doc is not None else None
        else:
            payload["document"] = None
        hm_audit_doc = _resume_variant_hm_audit_document(conn, str(row["id"]))
        payload["hm_audit_document"] = _serialize_document(hm_audit_doc) if hm_audit_doc is not None else None
    return payload


def list_resume_bases(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM resume_bases ORDER BY updated_at DESC, created_at DESC").fetchall()
    return {"items": [_serialize_resume_base(row) for row in rows], "total": len(rows)}


def create_resume_base(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    label = str(payload.get("label") or "").strip()
    source_path = str(payload.get("source_path") or "").strip() or None
    content_text = payload.get("content_text")
    if source_path and not content_text:
        source = Path(source_path).expanduser()
        if source.exists():
            content_text = source.read_text(encoding="utf-8")
    if not label or not str(content_text or "").strip():
        raise ValueError("label and content_text required")
    ts = now_iso()
    base_id = new_id()
    with connect(settings) as conn:
        conn.execute(
            "INSERT INTO resume_bases (id, label, source_path, content_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (base_id, label, source_path, str(content_text), ts, ts),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM resume_bases WHERE id = ?", (base_id,)).fetchone()
    return _serialize_resume_base(row)


def _load_resume_base(conn: sqlite3.Connection, base_id: str | None = None) -> sqlite3.Row:
    if base_id:
        row = conn.execute("SELECT * FROM resume_bases WHERE id = ?", (base_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM resume_bases ORDER BY updated_at DESC, created_at DESC LIMIT 1").fetchone()
    if row is None:
        raise KeyError("resume_base")
    return row


def _job_resume_context(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT jobs.id, jobs.title_raw, jobs.description_text, companies.name_raw AS company_name FROM jobs JOIN companies ON companies.id = jobs.company_id WHERE jobs.id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise KeyError(job_id)
    snapshot = conn.execute(
        "SELECT content_text FROM job_snapshots WHERE job_id = ? ORDER BY captured_at DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if snapshot is not None and snapshot["content_text"] and not row["description_text"]:
        row = dict(row)
        row["description_text"] = snapshot["content_text"]
    return row




def _resume_analysis_payload(*, job_id: str, job_title: str, company: str, base_id: str, base_label: str, source_text: str, job_text: str, phase: str) -> dict[str, Any]:
    jd_terms = _resume_terms_from_text(job_text)
    source_terms = set(_resume_terms_from_text(source_text))
    fabrication_guard_terms = [
        term for term in _fabrication_guard_terms_from_text(job_text)
        if term not in source_terms and term not in jd_terms
    ]
    present = [term for term in jd_terms if term in source_terms]
    missing = [term for term in jd_terms if term not in source_terms]
    safe_to_add = [term for term in missing if term in _KNOWN_CANDIDATE_SKILLS]
    cannot_add = [term for term in missing if term not in _KNOWN_CANDIDATE_SKILLS] + fabrication_guard_terms
    coverage = round((len(present) / len(jd_terms)) * 100, 1) if jd_terms else 0.0
    score = round(min(100.0, 40.0 + coverage * 0.6), 1)
    return {
        "job_id": job_id,
        "job_title": job_title,
        "company": company,
        "base_id": base_id,
        "base_label": base_label,
        "phase": phase,
        "score": score,
        "keyword_coverage": coverage,
        "present_keywords": present,
        "safe_to_add": safe_to_add,
        "cannot_add": cannot_add,
        "job_excerpt": job_text[:1200],
        "base_excerpt": source_text[:1200],
    }


def _store_resume_progress_event(conn: sqlite3.Connection, *, job_id: str, actor: str, step: str, task_id: str, variant_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
    payload = {"task_id": task_id, "step": step}
    if variant_id:
        payload["variant_id"] = variant_id
    if detail:
        payload.update(detail)
    _record_event(conn, job_id=job_id, event_type="resume.progress", actor=actor, detail=payload)


def _store_ats_analysis(conn: sqlite3.Connection, *, job_id: str, variant_id: str, phase: str, analysis: dict[str, Any]) -> None:
    conn.execute(
        "DELETE FROM ats_analyses WHERE resume_variant_id = ? AND phase = ?",
        (variant_id, phase),
    )
    conn.execute(
        "INSERT INTO ats_analyses (id, job_id, resume_variant_id, score, keyword_coverage, phase, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), job_id, variant_id, analysis["score"], analysis["keyword_coverage"], phase, _json_dumps(analysis), now_iso()),
    )


def _suggestions_from_analysis(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for term in analysis["safe_to_add"][:8]:
        suggestions.append({
            "kind": "keyword_alignment",
            "term": term,
            "suggestion_text": f"Emphasize verified experience with {term} in a role-aligned bullet or summary line.",
            "rationale": f"{term} appears in the job description and is within the allowed candidate skill inventory.",
            "safe": True,
        })
    for term in analysis["cannot_add"][:5]:
        suggestions.append({
            "kind": "fabrication_guard",
            "term": term,
            "suggestion_text": f"Do not add {term} unless it is already supported by the base resume or CV facts.",
            "rationale": f"{term} appears in the job description but is not in the allowed candidate skill inventory.",
            "safe": False,
        })
    return suggestions



def analyze_resume_fit(job_id: str, payload: dict[str, Any] | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    payload = payload or {}
    migrate_to_latest(settings)
    with connect(settings) as conn:
        base = _load_resume_base(conn, payload.get("base_id"))
        job = _job_resume_context(conn, job_id)
    base_text = str(base["content_text"] or "")
    job_text = f"{job['title_raw']}\n{job['description_text'] or ''}"
    analysis = _resume_analysis_payload(
        job_id=job_id,
        job_title=str(job["title_raw"]),
        company=str(job["company_name"]),
        base_id=str(base["id"]),
        base_label=str(base["label"]),
        source_text=base_text,
        job_text=job_text,
        phase="baseline",
    )
    analysis["suggestions"] = _suggestions_from_analysis(analysis)
    return analysis

def tailor_resume_for_job(job_id: str, payload: dict[str, Any] | None = None, actor: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    payload = payload or {}
    migrate_to_latest(settings)
    analysis = analyze_resume_fit(job_id, payload, settings)
    ts = now_iso()
    task_id = new_id()
    variant_id = new_id()
    document_id = new_id()
    label = str(payload.get("label") or f"{analysis['job_title']} tailored resume").strip()
    version_label = _variant_version_label(label, 1)
    variant_dir = settings.db_path.parent / "resume_variants"
    variant_dir.mkdir(parents=True, exist_ok=True)
    suggested_terms = analysis["safe_to_add"][:8]
    summary_lines = "\n".join(f"- {term}" for term in suggested_terms) if suggested_terms else "- No additional verified keywords identified."
    base_text = analysis["base_excerpt"]
    variant_text = (
        f"{base_text}\n\n"
        f"## Role Alignment Notes\n"
        f"Target role: {analysis['job_title']} at {analysis['company']}\n"
        f"Verified keywords to emphasize where truthful:\n{summary_lines}\n\n"
        f"## Fabrication Guard\n"
        f"Only weave in keywords already supported by Sai's verified experience and base resume facts.\n"
    )
    variant_path = variant_dir / f"{_slugify(analysis['company'])}-{_slugify(analysis['job_title'])}-{variant_id[:8]}.md"
    variant_path.write_text(variant_text, encoding='utf-8')
    file_sha256 = hashlib.sha256(variant_text.encode('utf-8')).hexdigest()
    with connect(settings) as conn:
        base = _load_resume_base(conn, analysis["base_id"])
        conn.execute(
            "INSERT INTO documents (id, kind, job_id, version_label, title, content_text, file_path, file_sha256, mime_type, generated_by, ats_keyword_coverage, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (document_id, "resume_variant", job_id, version_label, label, variant_text, str(variant_path), file_sha256, "text/markdown", "jobradar.resume", analysis["keyword_coverage"], ts, ts),
        )
        _store_resume_progress_event(conn, job_id=job_id, actor=actor, step="base_resolved", task_id=task_id, detail={"base_id": base["id"]})
        _store_resume_progress_event(conn, job_id=job_id, actor=actor, step="baseline_scored", task_id=task_id, detail={"score": analysis["score"]})
        conn.execute(
            "INSERT INTO resume_variants (id, job_id, base_id, label, content_text, source_text, pdf_document_id, compile_status, compiled_at, created_at, updated_at, revision, version_label, parent_variant_id, is_locked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (variant_id, job_id, base["id"], label, variant_text, variant_text, document_id, "draft", None, ts, ts, 1, version_label, None, 0),
        )
        _store_ats_analysis(conn, job_id=job_id, variant_id=variant_id, phase="baseline", analysis=analysis)
        _store_resume_progress_event(conn, job_id=job_id, actor=actor, step="variant_persisted", task_id=task_id, variant_id=variant_id)
        for suggestion in analysis["suggestions"]:
            conn.execute(
                "INSERT INTO resume_suggestions (id, job_id, resume_variant_id, suggestion_text, term, rationale, is_safe, status, applied_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), job_id, variant_id, suggestion["suggestion_text"], suggestion.get("term"), suggestion.get("rationale"), 1 if suggestion.get("safe") else 0, "pending", None, ts),
            )
        _store_resume_progress_event(conn, job_id=job_id, actor=actor, step="suggestions_generated", task_id=task_id, variant_id=variant_id, detail={"count": len(analysis["suggestions"])})
        _record_event(conn, job_id=job_id, event_type="resume.tailored", actor=actor, detail={"variant_id": variant_id, "base_id": base["id"], "document_id": document_id, "task_id": task_id})
        _store_resume_progress_event(conn, job_id=job_id, actor=actor, step="completed", task_id=task_id, variant_id=variant_id)
        conn.commit()
    result = get_resume_variant(variant_id, settings)
    result["task_id"] = task_id
    return result


def list_resume_variants_for_job(job_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM resume_variants WHERE job_id = ? ORDER BY updated_at DESC, created_at DESC",
            (job_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": len(rows)}


def get_resume_variant(variant_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM resume_variants WHERE id = ?", (variant_id,)).fetchone()
        if row is None:
            raise KeyError(variant_id)
        payload = _serialize_resume_variant(row, conn)
        payload["revision"] = row["revision"]
        payload["version_label"] = row["version_label"]
        payload["parent_variant_id"] = row["parent_variant_id"]
        payload["is_locked"] = bool(row["is_locked"])
        job = conn.execute("SELECT title_raw FROM jobs WHERE id = ?", (row["job_id"],)).fetchone()
        base = conn.execute("SELECT * FROM resume_bases WHERE id = ?", (row["base_id"],)).fetchone()
    payload["job_title"] = job["title_raw"] if job is not None else None
    payload["base"] = _serialize_resume_base(base) if base is not None else None
    return payload




def update_resume_variant_source(variant_id: str, source_text: str, actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    ts = now_iso()
    with connect(settings) as conn:
        row = _active_resume_variant_for_write(conn, variant_id, actor=actor, reason="source_edit")
        active_variant_id = str(row["id"])
        conn.execute(
            "UPDATE resume_variants SET source_text = ?, content_text = ?, compile_status = ?, updated_at = ? WHERE id = ?",
            (source_text, source_text, "draft", ts, active_variant_id),
        )
        doc_id = row["pdf_document_id"]
        if doc_id:
            file_path = conn.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if file_path and file_path["file_path"]:
                Path(file_path["file_path"]).write_text(source_text, encoding="utf-8")
            conn.execute(
                "UPDATE documents SET content_text = ?, mime_type = ?, generated_by = ?, updated_at = ? WHERE id = ?",
                (source_text, "text/markdown", "jobradar.resume.edit", ts, doc_id),
            )
        job = _job_resume_context(conn, str(row["job_id"]))
        base = _load_resume_base(conn, str(row["base_id"]))
        analysis = _resume_analysis_payload(
            job_id=str(row["job_id"]),
            job_title=str(job["title_raw"]),
            company=str(job["company_name"]),
            base_id=str(base["id"]),
            base_label=str(base["label"]),
            source_text=source_text,
            job_text=f"{job['title_raw']}\n{job['description_text'] or ''}",
            phase="working",
        )
        _store_ats_analysis(conn, job_id=str(row["job_id"]), variant_id=active_variant_id, phase="working", analysis=analysis)
        _record_event(conn, job_id=row["job_id"], event_type="resume.source_updated", actor=actor, detail={"variant_id": active_variant_id})
        conn.commit()
    return get_resume_variant(active_variant_id, settings)


def _append_safe_term(source_text: str, term: str) -> str:
    marker = f"- {term}"
    if marker in source_text or term in source_text:
        return source_text
    section = "\n\n## Accepted Safe Keywords\n"
    if section not in source_text:
        return source_text.rstrip() + section + marker + "\n"
    return source_text.rstrip() + "\n" + marker + "\n"


def accept_resume_suggestion(variant_id: str, suggestion_id: str, actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    ts = now_iso()
    with connect(settings) as conn:
        variant = _active_resume_variant_for_write(conn, variant_id, actor=actor, reason="suggestion_accept")
        active_variant_id = str(variant["id"])
        suggestion = conn.execute("SELECT * FROM resume_suggestions WHERE id = ? AND resume_variant_id = ?", (suggestion_id, active_variant_id)).fetchone()
        if suggestion is None:
            raise KeyError(suggestion_id)
        if not suggestion["is_safe"]:
            raise ValueError("unsafe_suggestion")
        source_text = str(variant["source_text"] or variant["content_text"] or "")
        updated = _append_safe_term(source_text, str(suggestion["term"] or suggestion["suggestion_text"]))
        conn.execute(
            "UPDATE resume_variants SET source_text = ?, content_text = ?, compile_status = ?, updated_at = ? WHERE id = ?",
            (updated, updated, "draft", ts, active_variant_id),
        )
        conn.execute(
            "UPDATE resume_suggestions SET status = ?, applied_at = ? WHERE id = ?",
            ("accepted", ts, suggestion_id),
        )
        doc_id = variant["pdf_document_id"]
        if doc_id:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if doc and doc["file_path"]:
                Path(doc["file_path"]).write_text(updated, encoding="utf-8")
            conn.execute("UPDATE documents SET content_text = ?, updated_at = ? WHERE id = ?", (updated, ts, doc_id))
        detail = {
            "accepted_suggestion_id": suggestion_id,
            "term": suggestion["term"],
            "status": "accepted",
        }
        conn.execute(
            "INSERT INTO ats_analyses (id, job_id, resume_variant_id, score, keyword_coverage, phase, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), variant["job_id"], active_variant_id, None, None, "accept_safe", _json_dumps(detail), ts),
        )
        _record_event(conn, job_id=variant["job_id"], event_type="resume.suggestion_accepted", actor=actor, detail={"variant_id": active_variant_id, "suggestion_id": suggestion_id, "term": suggestion["term"]})
        conn.commit()
    return get_resume_variant(active_variant_id, settings)


def accept_all_safe_resume_suggestions(variant_id: str, actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        variant = _active_resume_variant_for_write(conn, variant_id, actor=actor, reason="accept_all_safe")
        active_variant_id = str(variant["id"])
        rows = conn.execute(
            "SELECT id FROM resume_suggestions WHERE resume_variant_id = ? AND COALESCE(is_safe, 0) = 1 AND COALESCE(status, 'pending') != 'accepted' ORDER BY created_at ASC",
            (active_variant_id,),
        ).fetchall()
        conn.commit()
    for row in rows:
        accept_resume_suggestion(active_variant_id, str(row["id"]), actor=actor, settings=settings)
    return get_resume_variant(active_variant_id, settings)


def compile_resume_variant(variant_id: str, actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    ts = now_iso()
    with connect(settings) as conn:
        variant = _active_resume_variant_for_write(conn, variant_id, actor=actor, reason="compile")
        active_variant_id = str(variant["id"])
        document = conn.execute("SELECT * FROM documents WHERE id = ?", (variant["pdf_document_id"],)).fetchone() if variant["pdf_document_id"] else None
        source_text = str(variant["source_text"] or variant["content_text"] or "")
        compile_dir = settings.db_path.parent / "resume_variants" / "compiled"
        compile_dir.mkdir(parents=True, exist_ok=True)
        output_path = compile_dir / f"{active_variant_id}.html"
        html = "<html><head><meta charset='utf-8'><title>Resume Variant</title></head><body><pre style='white-space:pre-wrap;font-family:ui-monospace,monospace'>" + source_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</pre></body></html>"
        output_path.write_text(html, encoding="utf-8")
        file_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if document is None:
            doc_id = new_id()
            conn.execute(
                "INSERT INTO documents (id, kind, job_id, version_label, title, content_text, file_path, file_sha256, mime_type, generated_by, ats_keyword_coverage, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, "resume_compiled", variant["job_id"], f"compiled-{active_variant_id[:8]}", variant["label"], html, str(output_path), file_sha256, "text/html", "jobradar.resume.compile", None, ts, ts),
            )
            conn.execute("UPDATE resume_variants SET pdf_document_id = ? WHERE id = ?", (doc_id, active_variant_id))
        else:
            doc_id = str(document["id"])
            conn.execute(
                "UPDATE documents SET kind = ?, content_text = ?, file_path = ?, file_sha256 = ?, mime_type = ?, generated_by = ?, updated_at = ? WHERE id = ?",
                ("resume_compiled", html, str(output_path), file_sha256, "text/html", "jobradar.resume.compile", ts, doc_id),
            )
        conn.execute(
            "UPDATE resume_variants SET content_text = ?, compile_status = ?, compiled_at = ?, updated_at = ? WHERE id = ?",
            (source_text, "compiled", ts, ts, active_variant_id),
        )
        job = _job_resume_context(conn, str(variant["job_id"]))
        base = _load_resume_base(conn, str(variant["base_id"]))
        final_analysis = _resume_analysis_payload(
            job_id=str(variant["job_id"]),
            job_title=str(job["title_raw"]),
            company=str(job["company_name"]),
            base_id=str(base["id"]),
            base_label=str(base["label"]),
            source_text=source_text,
            job_text=f"{job['title_raw']}\n{job['description_text'] or ''}",
            phase="final",
        )
        final_analysis["compiled_document_id"] = doc_id
        final_analysis["compiled_file_path"] = str(output_path)
        _store_ats_analysis(conn, job_id=str(variant["job_id"]), variant_id=active_variant_id, phase="final", analysis=final_analysis)
        _record_event(conn, job_id=variant["job_id"], event_type="resume.compiled", actor=actor, detail={"variant_id": active_variant_id, "document_id": doc_id, "file_path": str(output_path)})
        conn.commit()
    return get_resume_variant(active_variant_id, settings)


def generate_resume_hm_audit(variant_id: str, actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    ts = now_iso()
    with connect(settings) as conn:
        variant = conn.execute("SELECT * FROM resume_variants WHERE id = ?", (variant_id,)).fetchone()
        if variant is None:
            raise KeyError(variant_id)
        job = _job_resume_context(conn, str(variant["job_id"]))
        base = _load_resume_base(conn, str(variant["base_id"]))
        analyses = conn.execute(
            "SELECT * FROM ats_analyses WHERE resume_variant_id = ? ORDER BY created_at DESC",
            (variant_id,),
        ).fetchall()
        latest = analyses[0] if analyses else None
        suggestions = conn.execute(
            "SELECT * FROM resume_suggestions WHERE resume_variant_id = ? ORDER BY created_at ASC",
            (variant_id,),
        ).fetchall()
        safe_terms = [str(row["term"] or row["suggestion_text"] or "").strip() for row in suggestions if row["is_safe"] and str(row["status"] or "pending") == "accepted"]
        blocked_terms = [str(row["term"] or row["suggestion_text"] or "").strip() for row in suggestions if not row["is_safe"]][:5]
        pending_safe_terms = [str(row["term"] or row["suggestion_text"] or "").strip() for row in suggestions if row["is_safe"] and str(row["status"] or "pending") != "accepted"][:5]
        score = float(latest["score"] or 0) if latest and latest["score"] is not None else None
        coverage = float(latest["keyword_coverage"] or 0) if latest and latest["keyword_coverage"] is not None else None
        verdict = "Strong pass"
        if blocked_terms or (coverage is not None and coverage < 55):
            verdict = "Needs revision"
        elif coverage is not None and coverage < 72:
            verdict = "Borderline"
        source_text = str(variant["source_text"] or variant["content_text"] or "")
        top_lines = [line.strip() for line in source_text.splitlines() if line.strip()][:6]
        strengths = top_lines[:3] or ["Resume contains usable role-aligned evidence."]
        improvements = []
        if pending_safe_terms:
            improvements.append(f"Weave in verified keywords still unused: {', '.join(pending_safe_terms[:4])}.")
        if blocked_terms:
            improvements.append(f"Do not claim unsupported requirements: {', '.join(blocked_terms[:4])}.")
        if coverage is not None and coverage < 72:
            improvements.append("Tighten alignment to the job description with clearer tool, impact, and incident examples.")
        if not improvements:
            improvements.append("Preserve current evidence quality and compress wording for recruiter skim speed.")
        audit_text = (
            f"# Hiring Manager Audit\n\n"
            f"- Verdict: {verdict}\n"
            f"- Job: {job['title_raw']}\n"
            f"- Company: {job['company_name']}\n"
            f"- Resume variant: {variant['label']}\n"
            f"- Revision: {variant['revision']}\n"
            f"- ATS score: {score if score is not None else 'n/a'}\n"
            f"- Keyword coverage: {coverage if coverage is not None else 'n/a'}\n\n"
            f"## What reads well\n" + "\n".join(f"- {item}" for item in strengths) + "\n\n"
            f"## Hiring concerns\n" + ("\n".join(f"- Unsupported or risky claim area: {item}" for item in blocked_terms) if blocked_terms else "- No unsupported-claim warnings are currently active.") + "\n\n"
            f"## Recommended next edits\n" + "\n".join(f"- {item}" for item in improvements) + "\n\n"
            f"## Verified signal inventory\n" + ("\n".join(f"- Accepted verified keyword: {item}" for item in safe_terms[:8]) if safe_terms else f"- Base resume: {base['label']}") + "\n"
        )
        doc = _resume_variant_hm_audit_document(conn, variant_id)
        audit_dir = settings.db_path.parent / "resume_variants" / "audits"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"{variant_id}-hm-audit.md"
        audit_path.write_text(audit_text, encoding="utf-8")
        doc_id = str(doc["id"]) if doc is not None else new_id()
        if doc is None:
            conn.execute(
                "INSERT INTO documents (id, kind, job_id, version_label, title, content_text, file_path, mime_type, generated_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, "hm_audit", variant["job_id"], f"{variant_id}-hm-audit", f"HM Audit · {variant['label']}", audit_text, str(audit_path), "text/markdown", "jobradar.resume.hm_audit", ts, ts),
            )
        else:
            conn.execute(
                "UPDATE documents SET title = ?, content_text = ?, file_path = ?, mime_type = ?, generated_by = ?, updated_at = ? WHERE id = ?",
                (f"HM Audit · {variant['label']}", audit_text, str(audit_path), "text/markdown", "jobradar.resume.hm_audit", ts, doc_id),
            )
        conn.execute(
            "INSERT INTO ats_analyses (id, job_id, resume_variant_id, score, keyword_coverage, phase, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), variant["job_id"], variant_id, score, coverage, "hm_audit", _json_dumps({"verdict": verdict, "document_id": doc_id}), ts),
        )
        _record_event(conn, job_id=variant["job_id"], event_type="resume.hm_audit_generated", actor=actor, detail={"variant_id": variant_id, "document_id": doc_id, "verdict": verdict})
        conn.commit()
    return get_resume_variant(variant_id, settings)


def get_resume_variant_download(variant_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        variant = conn.execute("SELECT * FROM resume_variants WHERE id = ?", (variant_id,)).fetchone()
        row = conn.execute(
            "SELECT documents.* FROM resume_variants JOIN documents ON documents.id = resume_variants.pdf_document_id WHERE resume_variants.id = ?",
            (variant_id,),
        ).fetchone()
        if row is None or variant is None:
            raise KeyError(variant_id)
        _record_event(conn, job_id=str(variant["job_id"]), event_type="resume.downloaded", actor="human", detail={"variant_id": variant_id, "document_id": row["id"]})
        conn.commit()
    return dict(row)



def get_resume_variant_ats(variant_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        variant = conn.execute("SELECT * FROM resume_variants WHERE id = ?", (variant_id,)).fetchone()
        if variant is None:
            raise KeyError(variant_id)
        rows = conn.execute(
            "SELECT * FROM ats_analyses WHERE resume_variant_id = ? ORDER BY created_at ASC",
            (variant_id,),
        ).fetchall()
    items = []
    for row in rows:
        payload = dict(row)
        try:
            payload["detail"] = json.loads(payload.get("detail_json") or "{}")
        except Exception:
            payload["detail"] = payload.get("detail_json")
        items.append(payload)
    return {"variant_id": variant_id, "job_id": variant["job_id"], "items": items}


def get_resume_events(job_id: str | None = None, variant_id: str | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    query = "SELECT id, job_id, event_type, actor, detail, occurred_at, created_at FROM application_events WHERE event_type LIKE 'resume.%'"
    params: list[Any] = []
    if job_id:
        query += " AND job_id = ?"
        params.append(job_id)
    query += " ORDER BY occurred_at DESC LIMIT 25"
    with connect(settings) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    items = []
    for row in rows:
        payload = dict(row)
        try:
            payload["detail"] = json.loads(payload.get("detail") or "{}")
        except Exception:
            payload["detail"] = payload.get("detail")
        if variant_id and str(payload.get("detail", {}).get("variant_id") or "") != variant_id:
            continue
        items.append(payload)
    return {"items": items, "total": len(items)}

def get_job_resume_workspace(job_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    analysis = analyze_resume_fit(job_id, settings=settings)
    variants = list_resume_variants_for_job(job_id, settings)
    job = get_job(job_id, settings)
    bases = list_resume_bases(settings)
    detailed_variants = [get_resume_variant(str(item["id"]), settings) for item in variants["items"]]
    return {
        "job": job,
        "analysis": analysis,
        "bases": bases["items"],
        "variants": detailed_variants,
        "events": get_resume_events(job_id=job_id, settings=settings)["items"],
    }

def _contact_links_for(conn: sqlite3.Connection, contact_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT id, job_id, application_id, role_in_process, created_at FROM contact_links WHERE contact_id = ? ORDER BY created_at ASC", (contact_id,)).fetchall()]


def _serialize_contact(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    payload = dict(row)
    payload["job_links"] = _contact_links_for(conn, str(row["id"]))
    return payload


def list_contacts(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM contacts ORDER BY updated_at DESC, created_at DESC").fetchall()
        items = [_serialize_contact(row, conn) for row in rows]
    return {"items": items, "total": len(items)}


def get_contact(contact_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        if row is None:
            raise KeyError(contact_id)
        return _serialize_contact(row, conn)


def _upsert_contact_links(conn: sqlite3.Connection, *, contact_id: str, payload: dict[str, Any], created_at: str) -> None:
    conn.execute("DELETE FROM contact_links WHERE contact_id = ?", (contact_id,))
    if payload.get("job_id") or payload.get("application_id"):
        conn.execute(
            "INSERT INTO contact_links (id, contact_id, job_id, application_id, role_in_process, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), contact_id, payload.get("job_id"), payload.get("application_id"), payload.get("relationship"), created_at),
        )


def create_contact(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name required")
    ts = now_iso()
    contact_id = new_id()
    with connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO contacts (
              id, company_id, name, title, email, profile_url, relationship, source,
              last_contacted_at, next_follow_up_at, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                payload.get("company_id"),
                name,
                payload.get("title"),
                payload.get("email"),
                payload.get("profile_url"),
                payload.get("relationship"),
                payload.get("source"),
                payload.get("last_contacted_at"),
                payload.get("next_follow_up_at"),
                payload.get("notes"),
                ts,
                ts,
            ),
        )
        _upsert_contact_links(conn, contact_id=contact_id, payload=payload, created_at=ts)
        conn.commit()
    return get_contact(contact_id, settings)


def update_contact(contact_id: str, payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name required")
    with connect(settings) as conn:
        exists = conn.execute("SELECT id FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        if exists is None:
            raise KeyError(contact_id)
        ts = now_iso()
        conn.execute(
            """
            UPDATE contacts
            SET company_id = ?, name = ?, title = ?, email = ?, profile_url = ?, relationship = ?,
                source = ?, last_contacted_at = ?, next_follow_up_at = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.get("company_id"),
                name,
                payload.get("title"),
                payload.get("email"),
                payload.get("profile_url"),
                payload.get("relationship"),
                payload.get("source"),
                payload.get("last_contacted_at"),
                payload.get("next_follow_up_at"),
                payload.get("notes"),
                ts,
                contact_id,
            ),
        )
        _upsert_contact_links(conn, contact_id=contact_id, payload=payload, created_at=ts)
        conn.commit()
    return get_contact(contact_id, settings)


def delete_contact(contact_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        deleted = conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
    if deleted.rowcount == 0:
        raise KeyError(contact_id)
    return {"ok": True, "id": contact_id}


def _serialize_interview(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    raw_ids = payload.get("interviewer_contact_ids")
    if raw_ids:
        try:
            payload["interviewer_contact_ids"] = json.loads(raw_ids)
        except Exception:
            payload["interviewer_contact_ids"] = []
    else:
        payload["interviewer_contact_ids"] = []
    return payload


def list_interviews(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM interviews ORDER BY scheduled_at DESC, created_at DESC").fetchall()
    items = [_serialize_interview(row) for row in rows]
    return {"items": items, "total": len(items)}


def get_interview(interview_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        if row is None:
            raise KeyError(interview_id)
    return _serialize_interview(row)


def create_interview(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    application_id = str(payload.get("application_id") or "").strip()
    round_type = str(payload.get("round_type") or "").strip()
    if not application_id or not round_type:
        raise ValueError("application_id and round_type required")
    interview_id = new_id()
    ts = now_iso()
    with connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO interviews (
              id, application_id, round_type, scheduled_at, duration_min, format, location_or_link,
              interviewer_contact_ids, prep_document_id, notes_document_id, outcome, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interview_id,
                application_id,
                round_type,
                payload.get("scheduled_at"),
                payload.get("duration_min"),
                payload.get("format"),
                payload.get("location_or_link"),
                _json_dumps(payload.get("interviewer_contact_ids") or []),
                payload.get("prep_document_id"),
                payload.get("notes_document_id"),
                payload.get("outcome"),
                ts,
                ts,
            ),
        )
        conn.commit()
    return get_interview(interview_id, settings)


def update_interview(interview_id: str, payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    application_id = str(payload.get("application_id") or "").strip()
    round_type = str(payload.get("round_type") or "").strip()
    if not application_id or not round_type:
        raise ValueError("application_id and round_type required")
    with connect(settings) as conn:
        exists = conn.execute("SELECT id FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        if exists is None:
            raise KeyError(interview_id)
        conn.execute(
            """
            UPDATE interviews
            SET application_id = ?, round_type = ?, scheduled_at = ?, duration_min = ?, format = ?,
                location_or_link = ?, interviewer_contact_ids = ?, prep_document_id = ?, notes_document_id = ?,
                outcome = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                application_id,
                round_type,
                payload.get("scheduled_at"),
                payload.get("duration_min"),
                payload.get("format"),
                payload.get("location_or_link"),
                _json_dumps(payload.get("interviewer_contact_ids") or []),
                payload.get("prep_document_id"),
                payload.get("notes_document_id"),
                payload.get("outcome"),
                now_iso(),
                interview_id,
            ),
        )
        conn.commit()
    return get_interview(interview_id, settings)


def delete_interview(interview_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        deleted = conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
        conn.commit()
    if deleted.rowcount == 0:
        raise KeyError(interview_id)
    return {"ok": True, "id": interview_id}


def import_manual_job(payload: dict[str, Any], actor: str = "human", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    source_url = str(payload.get("source_url") or payload.get("application_url") or "").strip()
    company_name = str(payload.get("company") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not source_url or not company_name or not title:
        raise ValueError("company, title, and source_url required")
    scan_id = create_scan("manual", "manual_import", settings)
    ingest_result = ingest_scan(
        scan_id,
        [
            {
                "source_platform": str(payload.get("source_platform") or "manual"),
                "source_url": source_url,
                "company": company_name,
                "title": title,
                "location": str(payload.get("location") or ""),
                "description_html": str(payload.get("description_html") or ""),
                "description_text": str(payload.get("description_text") or ""),
                "application_url": payload.get("application_url") or source_url,
                "salary_text": payload.get("salary_text"),
            }
        ],
        settings,
    )
    with connect(settings) as conn:
        row = conn.execute(
            "SELECT jobs.id, jobs.company_id FROM jobs JOIN job_sources ON job_sources.job_id = jobs.id WHERE job_sources.scan_id = ? ORDER BY job_sources.created_at DESC LIMIT 1",
            (scan_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("manual import produced no job")
        _record_event(conn, job_id=str(row["id"]), event_type="job.manual_imported", actor=actor, detail={"scan_id": scan_id})
        conn.commit()
    return {"scan_id": scan_id, "job_id": str(row["id"]), "company_id": str(row["company_id"]), **ingest_result}


def search_resources(query: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    q = str(query or "").strip()
    if not q:
        return {"query": q, "jobs": [], "companies": [], "contacts": [], "documents": []}
    with connect(settings) as conn:
        job_rows = conn.execute(
            """
            SELECT jobs.*, companies.name_raw AS company_name, companies.domain, companies.logo_url,
                   COUNT(job_sources.id) AS sources_count
            FROM jobs_fts
            JOIN jobs_fts_map ON jobs_fts_map.fts_rowid = jobs_fts.rowid
            JOIN jobs ON jobs.id = jobs_fts_map.job_id
            JOIN companies ON companies.id = jobs.company_id
            LEFT JOIN job_sources ON job_sources.job_id = jobs.id
            WHERE jobs_fts MATCH ?
            GROUP BY jobs.id
            ORDER BY jobs.discovered_at DESC
            LIMIT 10
            """,
            (q,),
        ).fetchall()
        like = f"%{q}%"
        company_rows = conn.execute(
            "SELECT * FROM companies WHERE name_raw LIKE ? OR name_normalized LIKE ? OR COALESCE(domain,'') LIKE ? ORDER BY priority DESC, name_raw ASC LIMIT 10",
            (like, like, like),
        ).fetchall()
        contact_rows = conn.execute(
            "SELECT * FROM contacts WHERE name LIKE ? OR COALESCE(email,'') LIKE ? OR COALESCE(title,'') LIKE ? ORDER BY updated_at DESC LIMIT 10",
            (like, like, like),
        ).fetchall()
        document_rows = conn.execute(
            "SELECT * FROM documents WHERE title LIKE ? OR COALESCE(content_text,'') LIKE ? ORDER BY updated_at DESC LIMIT 10",
            (like, like),
        ).fetchall()
        contacts = [_serialize_contact(row, conn) for row in contact_rows]
        companies = [_serialize_company(row) for row in company_rows]
        if not companies and job_rows:
            seen_company_ids: set[str] = set()
            for row in job_rows:
                company_id = str(row["company_id"])
                if company_id in seen_company_ids:
                    continue
                seen_company_ids.add(company_id)
                company = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
                if company is not None:
                    companies.append(_serialize_company(company))
    return {
        "query": q,
        "jobs": [_serialize_job_list_item(row) for row in job_rows],
        "companies": companies,
        "contacts": contacts,
        "documents": [_serialize_document(row) for row in document_rows],
    }


def get_db_summary(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    migrate_to_latest(settings)
    with connect(settings) as conn:
        counts = {}
        for table in [
            "companies", "scans", "scan_sources", "jobs", "job_sources", "job_locations", "job_snapshots",
            "documents", "applications", "application_events", "sponsorship_evidence", "contacts", "interviews",
            "automation_runs", "ingest_failures", "resume_bases", "resume_variants",
        ]:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_ok = conn.execute("PRAGMA foreign_key_check").fetchall() == []
    return {
        "status": "ok" if integrity == "ok" and fk_ok else "degraded",
        "schema_version": get_schema_version(settings),
        "counts": counts,
        "database": {
            "journal_mode": journal_mode,
            "integrity_check": integrity,
            "foreign_key_check_ok": fk_ok,
        },
        "privacy": {"contains_local_paths": False},
    }

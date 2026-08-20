from __future__ import annotations

import importlib
import json
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient


PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$cMOYn1VRSQP+v3AoOVujXg$dp1aIQue6dzvOmFs8v+92bk+bZzFVrjcvCB78plVio8"


def build_env(tmp_path: Path) -> dict[str, str]:
    source_dir = tmp_path / "processed"
    source_dir.mkdir(parents=True, exist_ok=True)
    sample = {
        "structured": {
            "title": "Associate SOC Analyst I",
            "company": "Rightworks",
            "location": "Nashua, NH",
            "salary": "nan",
            "link": "https://www.linkedin.com/jobs/view/4397140766",
            "source": "linkedin",
            "description": "Source: linkedin\\nAssociate SOC Analyst I\\n",
        },
        "record": {
            "reviewedAt": "2026-04-17T16:00:02Z",
            "jobId": "www-linkedin-com-jobs-view-4397140766",
            "title": "Associate SOC Analyst I",
            "company": "Rightworks",
            "location": "Nashua, NH",
            "salary": "nan",
            "link": "https://www.linkedin.com/jobs/view/4397140766",
            "source": "linkedin",
            "score": 69,
            "decision": "watch",
            "matchedSkills": ["soc"],
            "missingSkills": ["full job description unavailable"],
            "reasons": ["strong title alignment"],
            "notes": "Decision: watch",
            "sponsorshipStatus": "unknown",
            "authorizationRisk": "medium",
        },
    }
    (source_dir / "sample.json").write_text(json.dumps(sample), encoding="utf-8")
    return {
        "JOBRADAR_SECRET_KEY": "test-secret-key-32-bytes-minimum-value",
        "JOBRADAR_PASSWORD_HASH": PASSWORD_HASH,
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_BIND_HOST": "127.0.0.1",
        "JOBRADAR_BIND_PORT": "8765",
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(source_dir),
        "JOBRADAR_DISABLE_LOGIN": "false",
        "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "false",
    }


def load_db_module(tmp_path: Path):
    os.environ.update(build_env(tmp_path))
    module = importlib.import_module("jobradar_app.db")
    return importlib.reload(module)


def build_client(tmp_path: Path) -> TestClient:
    os.environ.update(build_env(tmp_path))
    module = importlib.import_module("jobradar_app.main")
    module = importlib.reload(module)
    return TestClient(module.create_app())


def test_migrate_to_latest_creates_section19_tables_and_pragmas(tmp_path: Path) -> None:
    db = load_db_module(tmp_path)

    db.migrate_to_latest()

    conn = db.connect()
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "companies",
            "scans",
            "scan_sources",
            "jobs",
            "job_sources",
            "job_locations",
            "job_snapshots",
            "documents",
            "applications",
            "application_events",
            "sponsorship_evidence",
            "h1b_employer_stats",
            "lca_records",
            "contacts",
            "contact_links",
            "interviews",
            "automation_runs",
            "analytics_cache",
            "ingest_failures",
            "user_preferences",
            "saved_filters",
            "app_users",
            "sessions",
            "resume_bases",
            "resume_variants",
            "ats_analyses",
            "resume_suggestions",
            "jobs_fts_map",
            "schema_migrations",
        }.issubset(tables)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.get_schema_version() == 13
    finally:
        conn.close()


def test_import_legacy_json_populates_summary_counts(tmp_path: Path) -> None:
    db = load_db_module(tmp_path)
    db.migrate_to_latest()

    imported = db.import_legacy_processed()

    assert imported["jobs_added"] == 1
    assert imported["companies_added"] == 1

    summary = db.get_db_summary()
    assert summary["schema_version"] == 13
    assert summary["counts"]["jobs"] == 1
    assert summary["counts"]["companies"] == 1
    assert summary["counts"]["job_sources"] == 1
    assert summary["counts"]["application_events"] >= 1
    assert summary["counts"]["resume_bases"] == 0
    assert "db_path" not in summary


def test_db_summary_api_requires_authentication(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/db/summary")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_db_summary_api_returns_counts_after_login(tmp_path: Path) -> None:
    db = load_db_module(tmp_path)
    db.migrate_to_latest()
    db.import_legacy_processed()
    client = build_client(tmp_path)

    login = client.post(
        "/auth/login",
        data={"password": "changeme-test-password"},
        follow_redirects=False,
    )
    assert login.status_code == 302

    response = client.get("/api/db/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 13
    assert body["counts"]["jobs"] == 1
    assert body["counts"]["companies"] == 1
    assert body["counts"]["job_sources"] == 1
    assert body["privacy"]["contains_local_paths"] is False

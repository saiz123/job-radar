from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$cMOYn1VRSQP+v3AoOVujXg$dp1aIQue6dzvOmFs8v+92bk+bZzFVrjcvCB78plVio8"


def build_env(tmp_path: Path) -> dict[str, str]:
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    return {
        "JOBRADAR_SECRET_KEY": "test-secret-key-32-bytes-minimum-value",
        "JOBRADAR_PASSWORD_HASH": PASSWORD_HASH,
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_BIND_HOST": "127.0.0.1",
        "JOBRADAR_BIND_PORT": "8765",
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(processed),
        "JOBRADAR_DISABLE_LOGIN": "false",
        "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "false",
    }


def load_modules(tmp_path: Path):
    os.environ.update(build_env(tmp_path))
    db = importlib.import_module("jobradar_app.db")
    main = importlib.import_module("jobradar_app.main")
    return importlib.reload(db), importlib.reload(main)


def build_client(tmp_path: Path) -> tuple[object, TestClient]:
    db, main = load_modules(tmp_path)
    return db, TestClient(main.create_app())


def login(client: TestClient) -> None:
    response = client.post("/auth/login", data={"password": "changeme-test-password"}, follow_redirects=False)
    assert response.status_code == 302


def write_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("jobradar_csrf", "")}


def test_scan_ingest_persists_jobs_sources_snapshots_and_events(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    assert created.status_code == 201
    scan_id = created.json()["scan_id"]

    payload = {
        "candidates": [
            {
                "source_platform": "greenhouse",
                "source_url": "https://boards.greenhouse.io/acme/jobs/12345?gh_src=abc&utm_source=x",
                "company": "The Acme, Inc.",
                "title": "SOC Analyst I - Remote (US)",
                "location": "Remote - US",
                "description_html": "<div data-on-load=\"@get('/api/export')\"><a href=\"https://example.com/job\">apply</a><p>First desc</p></div>",
                "description_text": "First desc",
            },
            {
                "source_platform": "greenhouse",
                "source_url": "https://job-boards.greenhouse.io/acme/jobs/12345",
                "company": "Acme",
                "title": "SOC Analyst I",
                "location": "Remote - US",
                "description_html": "<p>Longer legitimate description text here with SIEM triage and alert handling responsibilities.</p>",
                "description_text": "Longer legitimate description text here with SIEM triage and alert handling responsibilities.",
            },
        ]
    }

    ingested = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    assert ingested.status_code == 200
    body = ingested.json()
    assert body["jobs_added"] == 1
    assert body["jobs_updated"] == 1
    assert body["duplicates_merged"] == 1
    assert body["jobs_excluded"] == 0

    with db.connect() as conn:
        scan = conn.execute("SELECT status, jobs_added, jobs_updated, duplicates_merged FROM scans WHERE id = ?", (scan_id,)).fetchone()
        assert scan["status"] == "completed"
        assert scan["jobs_added"] == 1
        assert scan["jobs_updated"] == 1
        assert scan["duplicates_merged"] == 1

        job = conn.execute("SELECT duplicate_count, title_normalized, company_id, description_text FROM jobs").fetchone()
        assert job["duplicate_count"] == 2
        assert job["title_normalized"] == "soc analyst i"
        assert "Longer legitimate description text here" in job["description_text"]

        assert conn.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM job_snapshots WHERE capture_reason = 'discovery'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM application_events WHERE event_type = 'job.discovered'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM application_events WHERE event_type = 'job.merged'").fetchone()[0] == 1


def test_scan_ingest_records_ingest_failures_and_partial_status(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    scan_id = created.json()["scan_id"]

    payload = {
        "candidates": [
            {
                "source_platform": "lever",
                "source_url": "https://jobs.lever.co/acme/good/apply",
                "company": "Acme",
                "title": "Security Analyst",
                "location": "St. Louis, MO",
                "description_html": "<p>Normal role.</p>",
                "description_text": "Normal role.",
            },
            {
                "source_platform": "lever",
                "source_url": "",
                "company": "",
                "title": "",
                "location": "",
                "description_html": "<script>bad</script>",
                "description_text": "",
            },
        ]
    }

    ingested = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    assert ingested.status_code == 200
    body = ingested.json()
    assert body["jobs_added"] == 1
    assert body["failures"] == 1

    with db.connect() as conn:
        scan = conn.execute("SELECT status FROM scans WHERE id = ?", (scan_id,)).fetchone()
        assert scan["status"] == "partial"
        failure = conn.execute("SELECT stage, error, raw_payload FROM ingest_failures WHERE scan_id = ?", (scan_id,)).fetchone()
        assert failure["stage"] == "normalize"
        assert "missing required field" in failure["error"].lower()
        assert '"source_url": ""' in failure["raw_payload"]


def test_scan_ingest_is_idempotent_on_repeat_payload(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    scan_id = created.json()["scan_id"]
    payload = {
        "candidates": [
            {
                "source_platform": "greenhouse",
                "source_url": "https://boards.greenhouse.io/acme/jobs/99999?gh_src=abc",
                "company": "Acme",
                "title": "SOC Analyst I",
                "location": "Remote - US",
                "description_html": "<p>Desc</p>",
                "description_text": "Desc",
            }
        ]
    }

    first = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    second = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["jobs_added"] == 0
    assert second.json()["jobs_updated"] == 0

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0] == 1

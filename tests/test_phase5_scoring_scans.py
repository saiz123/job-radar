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


def test_scan_endpoints_expose_history_latest_and_scan_sources(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    assert created.status_code == 201
    scan_id = created.json()["scan_id"]

    payload = {
        "candidates": [
            {
                "source_platform": "greenhouse",
                "source_url": "https://job-boards.greenhouse.io/acme/jobs/12345",
                "company": "Acme",
                "title": "SOC Analyst I",
                "location": "Remote - US",
                "description_html": "<p>Security+ or equivalent. Splunk SIEM triage and alert monitoring.</p>",
                "description_text": "Security+ or equivalent. Splunk SIEM triage and alert monitoring.",
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

    by_id = client.get(f"/api/v1/scans/{scan_id}")
    assert by_id.status_code == 200
    by_id_body = by_id.json()
    assert by_id_body["id"] == scan_id
    assert by_id_body["status"] == "partial"
    assert len(by_id_body["scan_sources"]) == 2
    assert {item["status"] for item in by_id_body["scan_sources"]} == {"ok", "failed"}

    latest = client.get("/api/v1/scans/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == scan_id

    history = client.get("/api/v1/scans?limit=5")
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == scan_id

    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM scan_sources WHERE scan_id = ?", (scan_id,)).fetchone()[0]
        assert row == 2


def test_ingest_computes_sponsorship_score_tier_and_evidence(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)

    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO h1b_employer_stats (
              id, fiscal_year, employer_name, employer_name_normalized, city, state, naics,
              initial_approval, initial_denial, continuing_approval, continuing_denial, loaded_at, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "h1b-1", 2026, "Acme", "acme", None, None, None,
                14, 0, 0, 0, "2026-08-13T00:00:00+00:00", "https://uscis.example/fy2026.csv",
            ),
        )
        conn.commit()

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    scan_id = created.json()["scan_id"]
    payload = {
        "candidates": [
            {
                "source_platform": "greenhouse",
                "source_url": "https://job-boards.greenhouse.io/acme/jobs/777",
                "company": "Acme",
                "title": "SOC Analyst I",
                "location": "Remote - US",
                "description_html": "<p>CompTIA Security+ or equivalent required. Splunk SIEM triage, SOC alert monitoring, and Python scripting.</p>",
                "description_text": "CompTIA Security+ or equivalent required. Splunk SIEM triage, SOC alert monitoring, and Python scripting.",
            }
        ]
    }

    ingested = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    assert ingested.status_code == 200

    with db.connect() as conn:
        job = conn.execute(
            "SELECT sponsorship_class, sponsorship_confidence, personal_score, score_version, tier, liveness_status, fit_reasons, concerns, score_breakdown FROM jobs"
        ).fetchone()
        assert job["sponsorship_class"] in {"historically_possible", "likely"}
        assert job["sponsorship_confidence"] >= 0.60
        assert job["personal_score"] >= 40
        assert job["score_version"] == 1
        assert job["tier"] in {"C", "B", "A", "A+"}
        assert job["liveness_status"] == "New"
        assert "Security+" in job["fit_reasons"]
        assert job["concerns"]
        assert "evidence" in job["score_breakdown"]

        evidence = conn.execute(
            "SELECT signal_type, class_implied, evidence_text FROM sponsorship_evidence ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert evidence["class_implied"] in {"historically_possible", "likely"}
        assert evidence["signal_type"] == "h1b_history"
        assert "FY2026" in evidence["evidence_text"]


def test_ingest_hard_exclusion_forces_zero_score_and_restricted_sponsorship(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    scan_id = created.json()["scan_id"]
    payload = {
        "candidates": [
            {
                "source_platform": "greenhouse",
                "source_url": "https://job-boards.greenhouse.io/acme/jobs/999",
                "company": "Acme",
                "title": "Security Engineer",
                "location": "St. Louis, MO",
                "description_html": "<p>Active TS/SCI clearance required. U.S. citizenship required.</p>",
                "description_text": "Active TS/SCI clearance required. U.S. citizenship required.",
            }
        ]
    }

    ingested = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    assert ingested.status_code == 200

    with db.connect() as conn:
        job = conn.execute(
            "SELECT status, exclusion_reason, sponsorship_class, personal_score, tier FROM jobs"
        ).fetchone()
        assert job["status"] == "Excluded"
        assert job["exclusion_reason"] == "clearance_required"
        assert job["sponsorship_class"] == "clearance_required"
        assert job["personal_score"] == 0
        assert job["tier"] == "D"

from __future__ import annotations

import importlib
import json
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


def seed_job(client: TestClient) -> str:
    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=write_headers(client))
    assert created.status_code == 201
    scan_id = created.json()["scan_id"]
    payload = {
        "candidates": [
            {
                "source_platform": "greenhouse",
                "source_url": "https://job-boards.greenhouse.io/acme/jobs/777",
                "company": "Acme",
                "title": "SOC Analyst I",
                "location": "Remote - US",
                "description_html": "<p>CompTIA Security+ or equivalent required. Splunk SIEM triage and alert monitoring.</p>",
                "description_text": "CompTIA Security+ or equivalent required. Splunk SIEM triage and alert monitoring.",
            }
        ]
    }
    ingested = client.post(f"/api/v1/scans/{scan_id}/ingest", json=payload, headers=write_headers(client))
    assert ingested.status_code == 200
    jobs = client.get("/api/v1/jobs")
    assert jobs.status_code == 200
    return jobs.json()["items"][0]["id"]


def test_jobs_list_and_detail_return_enriched_records(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)
    job_id = seed_job(client)

    jobs = client.get("/api/v1/jobs")
    assert jobs.status_code == 200
    body = jobs.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "SOC Analyst I"
    assert body["items"][0]["company"]["name"] == "Acme"
    assert body["items"][0]["scores"]["version"] == 1
    assert body["items"][0]["sources_count"] == 1

    detail = client.get(f"/api/v1/jobs/{job_id}")
    assert detail.status_code == 200
    job = detail.json()
    assert job["id"] == job_id
    assert job["company"]["name"] == "Acme"
    assert len(job["sources"]) == 1
    assert len(job["snapshots"]) == 1
    assert len(job["events"]) >= 1
    assert job["sponsorship"]["class"]
    assert job["score_breakdown"]


def test_pipeline_move_updates_stage_and_writes_event(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)
    job_id = seed_job(client)

    board = client.get("/api/v1/pipeline")
    assert board.status_code == 200
    before = board.json()
    assert "Discovered" in before["columns"]
    assert before["columns"]["Discovered"][0]["id"] == job_id

    moved = client.patch(f"/api/v1/pipeline/{job_id}/move", json={"to_stage": "Saved", "position": 0}, headers=write_headers(client))
    assert moved.status_code == 200
    assert moved.json()["ok"] is True

    board_after = client.get("/api/v1/pipeline")
    assert board_after.status_code == 200
    assert board_after.json()["columns"]["Saved"][0]["id"] == job_id

    with db.connect() as conn:
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["status"] == "Saved"
        event = conn.execute("SELECT event_type, from_value, to_value FROM application_events WHERE job_id = ? AND event_type = 'stage.changed' ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
        assert event["from_value"] == "Discovered"
        assert event["to_value"] == "Saved"


def test_health_endpoint_reports_database_and_counts(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)
    seed_job(client)

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["database"]["jobs"] == 1
    assert body["checks"]["app"]["status"] == "ok"
    assert body["checks"]["datasets"]["status"] == "missing"
    assert body["checks"]["datasets"]["h1b_rows"] == 0

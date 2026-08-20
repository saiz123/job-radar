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
        "JOBRADAR_SERVICE_TOKEN": "service-token-test-value",
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_BIND_HOST": "127.0.0.1",
        "JOBRADAR_BIND_PORT": "8765",
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(processed),
        "JOBRADAR_SECURE_COOKIES": "false",
        "JOBRADAR_RUNNING_SCAN_STALE_AFTER_S": "3600",
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


def service_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer service-token-test-value",
        "X-JobRadar-Actor": "hermes",
    }


def seed_job(client: TestClient) -> str:
    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=service_headers())
    assert created.status_code == 201
    scan_id = created.json()["scan_id"]
    ingested = client.post(
        f"/api/v1/scans/{scan_id}/ingest",
        json={
            "candidates": [
                {
                    "source_platform": "greenhouse",
                    "source_url": "https://job-boards.greenhouse.io/acme/jobs/777",
                    "company": "Acme",
                    "title": "SOC Analyst I",
                    "location": "Remote - US",
                    "description_html": "<p>CompTIA Security+ required. Splunk SIEM triage, alert monitoring, incident response, vulnerability management, threat detection, cybersecurity analysis, security operations, cloud security, blue team support, and SIEM investigation in a fully remote US role.</p>",
                    "description_text": "CompTIA Security+ required. Splunk SIEM triage, alert monitoring, incident response, vulnerability management, threat detection, cybersecurity analysis, security operations, cloud security, blue team support, and SIEM investigation in a fully remote US role.",
                }
            ]
        },
        headers=service_headers(),
    )
    assert ingested.status_code == 200
    jobs = client.get("/api/v1/jobs", headers=service_headers())
    assert jobs.status_code == 200
    return jobs.json()["items"][0]["id"]


def test_evaluation_queue_and_evaluate_endpoint(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    job_id = seed_job(client)

    with db.connect() as conn:
        conn.execute("UPDATE jobs SET tier = 'B', personal_score = 72 WHERE id = ?", (job_id,))
        conn.commit()

    queue = client.get("/api/v1/jobs/evaluation-queue?limit=8", headers=service_headers())
    assert queue.status_code == 200
    queue_body = queue.json()
    assert queue_body["count"] == 1
    assert queue_body["items"][0]["id"] == job_id

    evaluated = client.post(
        f"/api/v1/jobs/{job_id}/evaluate",
        json={"report_number": 17, "career_ops_score": 4.4, "legitimacy": "strong"},
        headers=service_headers(),
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["ok"] is True

    queue_after = client.get("/api/v1/jobs/evaluation-queue?limit=8", headers=service_headers())
    assert queue_after.status_code == 200
    assert queue_after.json()["count"] == 0

    with db.connect() as conn:
        row = conn.execute(
            "SELECT career_ops_report_number, career_ops_score, career_ops_legitimacy FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row["career_ops_report_number"] == 17
        assert row["career_ops_score"] == 4.4
        assert row["career_ops_legitimacy"] == "strong"


def test_stale_running_scan_is_recovered_before_new_scan(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)

    with db.connect() as conn:
        ts = "2000-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO scans (id, mode, trigger, status, started_at, created_at) VALUES (?, ?, ?, 'running', ?, ?)",
            ("stale-scan", "portals", "manual", ts, ts),
        )
        conn.commit()

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=service_headers())

    assert created.status_code == 201
    assert created.json()["scan_id"] != "stale-scan"
    with db.connect() as conn:
        stale = conn.execute("SELECT status, finished_at, warnings FROM scans WHERE id = ?", ("stale-scan",)).fetchone()
        assert stale["status"] == "failed"
        assert stale["finished_at"] is not None
        assert "stale" in (stale["warnings"] or "").lower()


def test_sse_endpoint_streams_snapshot_for_authorized_browser_session(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login = client.post("/auth/login", data={"password": "changeme-test-password"}, follow_redirects=False)
    assert login.status_code == 302
    client.cookies.update(login.cookies)

    with client.stream("GET", "/api/v1/events") as response:
        chunks = list(response.iter_text())

    body = "".join(chunks)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: snapshot" in body
    assert '"type":"snapshot"' in body

def test_followups_digest_liveness_and_analytics_endpoints(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    job_id = seed_job(client)

    with db.connect() as conn:
        ts = db.now_iso()
        conn.execute(
            "INSERT INTO applications (id, job_id, stage, applied_at, follow_up_at, careerops_tracker_num, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db.new_id(), job_id, "Applied", ts, "2026-08-10T09:00:00Z", 17, "follow up soon", ts, ts),
        )
        conn.execute(
            "UPDATE jobs SET status = ?, last_verified_at = ?, career_ops_report_number = ?, career_ops_score = ?, career_ops_legitimacy = ? WHERE id = ?",
            ("Applied", "2026-08-01T00:00:00Z", 17, 4.4, "strong", job_id),
        )
        conn.commit()

    followups = client.get("/api/v1/followups/due", headers=service_headers())
    assert followups.status_code == 200
    followup_body = followups.json()
    assert followup_body["total"] == 1
    assert followup_body["items"][0]["job_id"] == job_id

    digest = client.get("/api/v1/digest?since=24h", headers=service_headers())
    assert digest.status_code == 200
    digest_body = digest.json()
    assert digest_body["new_jobs_count"] == 1
    assert digest_body["top_jobs"][0]["id"] == job_id
    assert digest_body["followups_due_count"] == 1

    liveness = client.post("/api/v1/jobs/liveness", json={}, headers=service_headers())
    assert liveness.status_code == 200
    liveness_body = liveness.json()
    assert liveness_body["ok"] is True
    assert liveness_body["checked"] >= 1

    analytics = client.get("/api/v1/analytics?window=90d", headers=service_headers())
    assert analytics.status_code == 200
    analytics_body = analytics.json()
    assert analytics_body["window"] == "90d"
    assert analytics_body["applications_sent"] == 1
    assert analytics_body["by_status"]["Applied"] >= 1
    assert analytics_body["by_stage"]["Applied"] == 1
    assert analytics_body["funnel"]["applied"] == 1
    assert analytics_body["funnel"]["small_sample"] is True
    assert analytics_body["followup_compliance"]["tracked"] == 1
    assert analytics_body["followup_compliance"]["due_open"] == 1
    assert analytics_body["resume_attribution"][0]["applications"] == 1
    assert analytics_body["warnings"]


def test_two_strong_soc_jobs_enter_evaluation_queue_without_manual_promotion(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"}, headers=service_headers())
    assert created.status_code == 201
    scan_id = created.json()["scan_id"]

    ingested = client.post(
        f"/api/v1/scans/{scan_id}/ingest",
        json={
            "candidates": [
                {
                    "source_platform": "manual-seed",
                    "source_url": "https://example.com/jobs/seed-soc-1",
                    "application_url": "https://example.com/jobs/seed-soc-1",
                    "company": "Seed Acme Security",
                    "title": "SOC Analyst I - Remote (US)",
                    "location": "Remote - US",
                    "description_html": "<p>SOC analyst role with SIEM, triage, alert monitoring, Splunk, Python, Security+ or equivalent. Entry level.</p>",
                    "description_text": "SOC analyst role with SIEM, triage, alert monitoring, Splunk, Python, Security+ or equivalent. Entry level.",
                },
                {
                    "source_platform": "manual-seed",
                    "source_url": "https://example.com/jobs/seed-soc-2",
                    "application_url": "https://example.com/jobs/seed-soc-2",
                    "company": "Seed Bravo Cyber",
                    "title": "Security Analyst (SOC) - Remote US",
                    "location": "Remote - US",
                    "description_html": "<p>Security analyst for SOC operations, SIEM investigations, alert triage, Sentinel, Python, Security+ required.</p>",
                    "description_text": "Security analyst for SOC operations, SIEM investigations, alert triage, Sentinel, Python, Security+ required.",
                },
            ]
        },
        headers=service_headers(),
    )
    assert ingested.status_code == 200

    queue = client.get("/api/v1/jobs/evaluation-queue?limit=10", headers=service_headers())
    assert queue.status_code == 200
    queue_body = queue.json()
    assert queue_body["count"] == 2
    assert {item["company"]["name"] for item in queue_body["items"]} == {"Seed Acme Security", "Seed Bravo Cyber"}


def test_evaluate_endpoint_hydrates_score_and_legitimacy_from_report_when_only_report_number_is_posted(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    job_id = seed_job(client)

    report_dir = tmp_path / "career-ops" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "042-acme-soc-analyst-i-2026-08-13.md").write_text(
        "# Report\n\n"
        "**URL:** https://example.com/jobs/42\n\n"
        "**Legitimacy:** High Confidence\n\n"
        "## Machine Summary\n"
        "```yaml\n"
        "report_number: 42\n"
        "company: Acme\n"
        "title: SOC Analyst I\n"
        "score: 4.4\n"
        "legitimacy: High Confidence\n"
        "reasons:\n"
        "  - Strong SOC title alignment\n"
        "concerns:\n"
        "  - Sponsorship unclear\n"
        "url: https://example.com/jobs/42\n"
        "```\n",
        encoding="utf-8",
    )

    os.environ["JOBRADAR_CAREEROPS_ROOT"] = str(tmp_path / "career-ops")
    os.environ["JOBRADAR_NODE_BIN"] = "/usr/bin/node"

    evaluated = client.post(
        f"/api/v1/jobs/{job_id}/evaluate",
        json={"report_number": 42},
        headers=service_headers(),
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["ok"] is True

    detail = client.get(f"/api/v1/jobs/{job_id}", headers=service_headers())
    assert detail.status_code == 200
    body = detail.json()
    assert body["scores"]["career_ops"] == 4.4
    assert body["events"][0]["event_type"] == "job.evaluated"
    assert body["events"][0]["detail"] is not None

    db, _client2 = build_client(tmp_path)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT career_ops_report_number, career_ops_score, career_ops_legitimacy FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row["career_ops_report_number"] == 42
        assert row["career_ops_score"] == 4.4
        assert row["career_ops_legitimacy"] == "High Confidence"

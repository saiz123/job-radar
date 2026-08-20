from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path

from fastapi.testclient import TestClient


PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$cMOYn1VRSQP+v3AoOVujXg$dp1aIQue6dzvOmFs8v+92bk+bZzFVrjcvCB78plVio8"


def make_careerops_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "career-ops"
    for rel in ["data", "reports", "templates", "batch/tracker-additions", "bin", "run"]:
        (root / rel).mkdir(parents=True, exist_ok=True)

    (root / "templates" / "states.yml").write_text(
        "states:\n"
        "  - id: evaluated\n"
        "    label: Evaluated\n"
        "  - id: applied\n"
        "    label: Applied\n"
        "  - id: responded\n"
        "    label: Responded\n"
        "  - id: interview\n"
        "    label: Interview\n"
        "  - id: offer\n"
        "    label: Offer\n"
        "  - id: rejected\n"
        "    label: Rejected\n"
        "  - id: discarded\n"
        "    label: Discarded\n"
        "  - id: skip\n"
        "    label: SKIP\n",
        encoding="utf-8",
    )
    (root / "data" / "applications.md").write_text(
        "# Career-Ops Applications\n\n"
        "| # | Date | Company | Via | Role | Score | Status | PDF | Report | Notes |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    (root / "data" / "pipeline.md").write_text("# Career-Ops Job Inbox\n\n## Pending\n\n", encoding="utf-8")
    (root / "data" / "status-log.tsv").write_text("", encoding="utf-8")
    (root / "data" / "follow-ups.md").write_text("# Follow-ups\n\n", encoding="utf-8")
    (root / "reports" / "042-acme-soc-analyst-i-2026-08-13.md").write_text(
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

    node = root / "bin" / "node"
    node.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "root = Path.cwd()\n"
        "script = Path(sys.argv[1]).name\n"
        "args = sys.argv[2:]\n"
        "if script == 'reserve-report-num.mjs':\n"
        "    if '--release' in args:\n"
        "        print('released')\n"
        "    else:\n"
        "        print('043-043')\n"
        "elif script == 'merge-tracker.mjs':\n"
        "    print('merged')\n"
        "elif script == 'tracker.mjs' and len(args) == 1 and args[0] == 'sync':\n"
        "    print('synced')\n"
        "elif script == 'set-status.mjs':\n"
        "    print('status updated')\n"
        "elif script == 'doctor.mjs':\n"
        "    print(json.dumps({'onboardingNeeded': False, 'missing': [], 'warnings': []}))\n"
        "elif script == 'stats.mjs':\n"
        "    print(json.dumps({'applications': 0, 'reports': 1}))\n"
        "else:\n"
        "    raise SystemExit(f'unsupported script: {script}')\n",
        encoding="utf-8",
    )
    node.chmod(node.stat().st_mode | stat.S_IEXEC)
    return root


def build_env(tmp_path: Path) -> dict[str, str]:
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    careerops_root = make_careerops_fixture(tmp_path)
    return {
        "JOBRADAR_SECRET_KEY": "test-secret-key-32-bytes-minimum-value",
        "JOBRADAR_PASSWORD_HASH": PASSWORD_HASH,
        "JOBRADAR_SERVICE_TOKEN": "service-token-test-value",
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_BIND_HOST": "127.0.0.1",
        "JOBRADAR_BIND_PORT": "8765",
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(processed),
        "JOBRADAR_DISABLE_LOGIN": "false",
        "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "false",
        "JOBRADAR_CAREEROPS_ROOT": str(careerops_root),
        "JOBRADAR_NODE_BIN": str(careerops_root / "bin" / "node"),
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


def human_confirmed_headers() -> dict[str, str]:
    return {
        **service_headers(),
        "X-JobRadar-Human-Confirmed": "true",
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
                    "application_url": "https://job-boards.greenhouse.io/acme/jobs/777/apply",
                    "company": "Acme",
                    "title": "SOC Analyst I",
                    "location": "Remote - US",
                    "description_html": "<p>CompTIA Security+ required. Splunk SIEM triage and SOC alert monitoring.</p>",
                    "description_text": "CompTIA Security+ required. Splunk SIEM triage and SOC alert monitoring.",
                }
            ]
        },
        headers=service_headers(),
    )
    assert ingested.status_code == 200
    jobs = client.get("/api/v1/jobs", headers=service_headers())
    assert jobs.status_code == 200
    return jobs.json()["items"][0]["id"]


def test_prepare_endpoint_persists_application_documents_and_tracker_paths(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    job_id = seed_job(client)

    prepared = client.post(
        f"/api/v1/jobs/{job_id}/prepare",
        json={
            "resume_document": {"path": "/tmp/Sai_Teja_Kavuri_SOC_Analyst.pdf", "title": "Tailored Resume"},
            "cover_letter_document": {"path": "/tmp/acme-cover-letter.pdf", "title": "Cover Letter"},
            "answers_document": {"path": "/tmp/acme-answers.md", "title": "Screening Answers"},
            "notes": "tailored package ready",
            "next_action": "review package",
        },
        headers=service_headers(),
    )

    assert prepared.status_code == 200
    body = prepared.json()
    assert body["ok"] is True
    assert body["stage"] == "ReadyToApply"
    assert body["task_id"]

    detail = client.get(f"/api/v1/jobs/{job_id}", headers=service_headers())
    assert detail.status_code == 200
    job = detail.json()
    assert job["status"] == "ReadyToApply"
    assert job["application"]["stage"] == "ReadyToApply"
    assert len(job["documents"]) == 3
    assert {item["kind"] for item in job["documents"]} == {"resume", "cover_letter", "screening_answers"}

    with db.connect() as conn:
        app = conn.execute(
            "SELECT stage, careerops_tracker_num, next_action, notes FROM applications WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        assert app["stage"] == "ReadyToApply"
        assert app["careerops_tracker_num"] == 43
        assert app["next_action"] == "review package"
        assert app["notes"] == "tailored package ready"
        doc_count = conn.execute("SELECT COUNT(*) FROM documents WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert doc_count == 3
        events = conn.execute(
            "SELECT event_type FROM application_events WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        ).fetchall()
        assert [row["event_type"] for row in events][-2:] == ["stage.changed", "application.prepared"]

    additions = list((tmp_path / "career-ops" / "batch" / "tracker-additions").glob("043-acme.tsv"))
    assert len(additions) == 1


def test_apply_endpoint_requires_human_confirmation_for_service_actor(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    job_id = seed_job(client)

    response = client.post(f"/api/v1/jobs/{job_id}/apply", json={}, headers=service_headers())

    assert response.status_code == 403
    assert response.json()["error"] == "human_confirmation_required"


def test_apply_status_and_followup_workflow_persist_and_sync(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    job_id = seed_job(client)

    prepared = client.post(
        f"/api/v1/jobs/{job_id}/prepare",
        json={"resume_document": {"path": "/tmp/Sai_Teja_Kavuri_SOC_Analyst.pdf"}},
        headers=service_headers(),
    )
    assert prepared.status_code == 200
    application_id = prepared.json()["application_id"]

    applied = client.post(
        f"/api/v1/jobs/{job_id}/apply",
        json={
            "follow_up_at": "2026-08-20T09:00:00Z",
            "notes": "submitted manually",
            "applied_via": "employer_site",
        },
        headers=human_confirmed_headers(),
    )
    assert applied.status_code == 200
    assert applied.json()["stage"] == "Applied"

    status_changed = client.post(
        f"/api/v1/jobs/{job_id}/status",
        json={"stage": "Responded", "note": "recruiter replied", "follow_up_at": "2026-08-27T09:00:00Z"},
        headers=service_headers(),
    )
    assert status_changed.status_code == 200
    assert status_changed.json()["stage"] == "Responded"

    due = client.get("/api/v1/followups/due?window=30d", headers=service_headers())
    assert due.status_code == 200
    due_item = due.json()["items"][0]
    assert due_item["application_id"] == application_id
    assert due_item["due_state"] == "upcoming"

    completed = client.post(
        f"/api/v1/followups/{application_id}/complete",
        json={
            "contact_at": "2026-08-27T09:30:00Z",
            "next_follow_up_at": "2026-09-03T09:00:00Z",
            "note": "sent follow-up email",
        },
        headers=service_headers(),
    )
    assert completed.status_code == 200
    assert completed.json()["ok"] is True

    with db.connect() as conn:
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["status"] == "Responded"
        app = conn.execute(
            "SELECT stage, applied_via, follow_up_at, last_contact_at, response_at FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        assert app["stage"] == "Responded"
        assert app["applied_via"] == "employer_site"
        assert app["follow_up_at"] == "2026-09-03T09:00:00Z"
        assert app["last_contact_at"] == "2026-08-27T09:30:00Z"
        assert app["response_at"] is not None
        events = conn.execute(
            "SELECT event_type, to_value FROM application_events WHERE application_id = ? ORDER BY created_at ASC",
            (application_id,),
        ).fetchall()
        event_types = [row["event_type"] for row in events]
        assert "application.applied" in event_types
        assert "application.status_changed" in event_types
        assert "followup.completed" in event_types
        runs = [row[0] for row in conn.execute("SELECT name FROM automation_runs ORDER BY started_at ASC").fetchall()]
        assert "set-status.mjs" in runs
        assert "tracker.mjs" in runs
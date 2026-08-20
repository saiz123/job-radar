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
    careerops = tmp_path / "career-ops"
    (careerops / "data").mkdir(parents=True, exist_ok=True)
    (careerops / "bin").mkdir(parents=True, exist_ok=True)
    (careerops / "data" / "pipeline.md").write_text("# Career-Ops Job Inbox\n\n## Pending\n\n- [ ] https://example.com/jobs/pending | Acme | SOC Analyst I | Remote\n", encoding="utf-8")
    (careerops / "data" / "scan-runs.tsv").write_text("2026-08-13T10:00:00Z\tfull\tcompleted\t10\t2\n", encoding="utf-8")
    node = careerops / "bin" / "node"
    node.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "script = Path(sys.argv[1]).name\n"
        "if script == 'doctor.mjs':\n"
        "    print(json.dumps({'onboardingNeeded': False, 'missing': [], 'warnings': []}))\n"
        "elif script == 'stats.mjs':\n"
        "    print(json.dumps({'applications': 1, 'reports': 1}))\n"
        "else:\n"
        "    raise SystemExit(f'unsupported script: {script}')\n",
        encoding="utf-8",
    )
    node.chmod(0o755)
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    (cron_dir / "ticker_heartbeat").write_text(str(__import__('time').time()), encoding="utf-8")
    (cron_dir / "jobs.json").write_text(json.dumps({"jobs": [{"id": "jobradar-discover-1", "name": "jobradar-discover", "enabled": True, "deliver": "local", "last_status": "ok", "next_run_at": "2026-08-14T07:00:00-05:00", "last_run_at": "2026-08-13T07:00:00-05:00"}]}), encoding="utf-8")
    return {
        "JOBRADAR_SECRET_KEY": "test-secret-key-32-bytes-minimum-value",
        "JOBRADAR_PASSWORD_HASH": PASSWORD_HASH,
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_BIND_HOST": "127.0.0.1",
        "JOBRADAR_BIND_PORT": "8765",
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(processed),
        "JOBRADAR_CAREEROPS_ROOT": str(careerops),
        "JOBRADAR_NODE_BIN": str(node),
        "JOBRADAR_CRON_DIR": str(cron_dir),
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


def login(client: TestClient) -> None:
    response = client.post("/auth/login", data={"password": "changeme-test-password"}, follow_redirects=False)
    assert response.status_code == 302
    client.cookies.update(response.cookies)


def seed_scan_with_failure(client: TestClient) -> str:
    csrf = client.cookies.get("jobradar_csrf", "")
    created = client.post(
        "/api/v1/scans",
        json={"mode": "portals", "trigger": "manual"},
        headers={"X-CSRF-Token": csrf},
    )
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
                    "description_html": "<p>Security+ or equivalent</p>",
                    "description_text": "Security+ or equivalent",
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
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert ingested.status_code == 200
    return scan_id


def test_automation_status_and_runs_expose_scan_and_run_history(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)
    scan_id = seed_scan_with_failure(client)

    with db.connect() as conn:
        ts = db.now_iso()
        conn.execute(
            "INSERT INTO automation_runs (id, kind, name, scan_id, argv, exit_code, duration_ms, stdout_head, stderr_head, status, started_at, finished_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                db.new_id(),
                "careerops",
                "doctor.mjs",
                scan_id,
                json.dumps(["node", "doctor.mjs"]),
                0,
                1234,
                "ok",
                "",
                "completed",
                ts,
                ts,
                ts,
            ),
        )
        conn.commit()

    status = client.get("/api/v1/automation/status")
    assert status.status_code == 200
    body = status.json()
    assert body["latest_scan"]["id"] == scan_id
    assert body["latest_scan"]["status"] == "partial"
    assert body["run_counts"]["completed"] >= 1
    assert body["failure_counts"]["unresolved"] == 1

    runs = client.get("/api/v1/automation/runs?limit=5")
    assert runs.status_code == 200
    run_body = runs.json()
    names = [item["name"] for item in run_body["items"]]
    assert "doctor.mjs" in names
    assert "stats.mjs" in names
    assert any(item["status"] == "completed" for item in run_body["items"])


def test_automation_failures_and_retry_flow(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)
    scan_id = seed_scan_with_failure(client)

    failures = client.get("/api/v1/automation/failures")
    assert failures.status_code == 200
    body = failures.json()
    assert len(body["items"]) == 1
    failure_id = body["items"][0]["id"]

    retried = client.post(
        f"/api/v1/automation/failures/{failure_id}/retry",
        headers={"X-CSRF-Token": client.cookies.get("jobradar_csrf", "")},
    )
    assert retried.status_code == 200
    retry_body = retried.json()
    assert retry_body["ok"] is True
    assert retry_body["resolved"] is True
    assert retry_body["failure_id"] == failure_id

    failures_after = client.get("/api/v1/automation/failures")
    assert failures_after.status_code == 200
    assert failures_after.json()["items"] == []

    with db.connect() as conn:
        failure = conn.execute("SELECT resolved FROM ingest_failures WHERE id = ?", (failure_id,)).fetchone()
        assert failure["resolved"] == 1
        run = conn.execute("SELECT kind, status, name FROM automation_runs WHERE kind = 'ingest_retry' ORDER BY started_at DESC LIMIT 1").fetchone()
        assert run["status"] == "completed"
        assert run["name"] == "retry_failure"


def test_write_endpoints_require_csrf_for_browser_session(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)

    created = client.post("/api/v1/scans", json={"mode": "portals", "trigger": "manual"})

    assert created.status_code == 403
    assert created.json()["error"] == "csrf_required"


def test_readyz_reports_db_and_adapter_state_without_auth(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)

    response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["database"] == "ok"
    assert body["adapter"] == "ok"


def test_health_reports_real_scheduler_and_careerops_state(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["careerops"]["status"] == "ok"
    assert body["checks"]["careerops"]["onboarding_needed"] is False
    assert body["checks"]["careerops"]["pipeline_pending"] == 1
    assert body["checks"]["scheduler"]["gateway_running"] is True
    assert body["checks"]["scheduler"]["jobs"] == 1
    assert body["checks"]["scheduler"]["items"][0]["name"] == "jobradar-discover"

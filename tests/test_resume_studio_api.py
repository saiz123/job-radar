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
        "JOBRADAR_DISABLE_LOGIN": "false",
        "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "false",
        "JOBRADAR_CAREEROPS_ROOT": "",
        "JOBRADAR_NODE_BIN": "",
    }


def build_client(tmp_path: Path):
    os.environ.update(build_env(tmp_path))
    db = importlib.import_module("jobradar_app.db")
    main = importlib.import_module("jobradar_app.main")
    return importlib.reload(db), TestClient(importlib.reload(main).create_app())


def login(client: TestClient) -> None:
    response = client.post("/auth/login", data={"password": "changeme-test-password"}, follow_redirects=False)
    assert response.status_code == 302


def write_headers(client: TestClient) -> dict[str, str]:
    csrf = client.cookies.get("jobradar_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


def create_manual_job(client: TestClient) -> str:
    response = client.post(
        "/api/v1/jobs/manual",
        headers=write_headers(client),
        json={
            "company": "Acme Security",
            "title": "SOC Analyst I",
            "location": "Remote - US",
            "source_platform": "manual",
            "source_url": "https://example.com/jobs/acme-soc-1",
            "application_url": "https://example.com/jobs/acme-soc-1/apply",
            "description_text": "Splunk SIEM triage, Microsoft Sentinel investigation, Python scripting, CompTIA Security+, and CrowdStrike Falcon required.",
            "description_html": "<p>Splunk SIEM triage, Microsoft Sentinel investigation, Python scripting, CompTIA Security+, and CrowdStrike Falcon required.</p>",
        },
    )
    assert response.status_code == 201
    return response.json()["job_id"]


def test_resume_base_analyze_and_tailor_flow(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)
    job_id = create_manual_job(client)

    created_base = client.post(
        "/api/v1/resume/bases",
        headers=write_headers(client),
        json={
            "label": "Master Resume",
            "content_text": "Sai Teja Kavuri\nSOC analyst with Splunk SIEM triage, Python scripting, Wazuh, and incident response experience.",
        },
    )
    assert created_base.status_code == 201
    base_id = created_base.json()["id"]

    bases = client.get("/api/v1/resume/bases")
    assert bases.status_code == 200
    assert bases.json()["total"] == 1

    analysis = client.post(
        "/api/v1/resume/analyze",
        headers=write_headers(client),
        json={"job_id": job_id, "base_id": base_id},
    )
    assert analysis.status_code == 200
    body = analysis.json()
    assert body["job_id"] == job_id
    assert "Splunk" in body["present_keywords"]
    assert "Microsoft Sentinel" in body["safe_to_add"]
    assert body["keyword_coverage"] > 0
    assert body["suggestions"]

    tailored = client.post(
        "/api/v1/resume/tailor",
        headers=write_headers(client),
        json={"job_id": job_id, "base_id": base_id, "label": "Acme SOC Resume"},
    )
    assert tailored.status_code == 201
    variant = tailored.json()
    variant_id = variant["id"]
    assert variant["label"] == "Acme SOC Resume"
    assert variant["document"]["kind"] == "resume_variant"
    assert "Role Alignment Notes" in variant["content_text"]
    assert variant["ats_analyses"]
    assert variant["suggestions"]

    variant_detail = client.get(f"/api/v1/resume/variants/{variant_id}")
    assert variant_detail.status_code == 200
    variant_detail_body = variant_detail.json()
    assert variant_detail_body["id"] == variant_id
    safe_suggestion = next(item for item in variant_detail_body["suggestions"] if item["is_safe"])
    blocked_suggestion = next(item for item in variant_detail_body["suggestions"] if not item["is_safe"])

    blocked = client.post(
        f"/api/v1/resume/variants/{variant_id}/suggestions/{blocked_suggestion['id']}",
        headers=write_headers(client),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"] == "unsafe_suggestion"

    accepted = client.post(
        f"/api/v1/resume/variants/{variant_id}/suggestions/{safe_suggestion['id']}",
        headers=write_headers(client),
    )
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    accepted_row = next(item for item in accepted_body["suggestions"] if item["id"] == safe_suggestion["id"])
    assert accepted_row["status"] == "accepted"
    assert safe_suggestion["term"] in accepted_body["content_text"]

    edited = client.patch(
        f"/api/v1/resume/variants/{variant_id}/source",
        headers=write_headers(client),
        json={"source_text": accepted_body["content_text"] + "\nEdited by test.\n"},
    )
    assert edited.status_code == 200
    assert "Edited by test." in edited.json()["content_text"]

    compiled = client.post(
        f"/api/v1/resume/variants/{variant_id}/compile",
        headers=write_headers(client),
    )
    assert compiled.status_code == 200
    compiled_body = compiled.json()
    assert compiled_body["compile_status"] == "compiled"
    assert compiled_body["document"]["mime_type"] == "text/html"
    download = client.get(f"/api/v1/resume/variants/{variant_id}/download")
    assert download.status_code == 200
    assert "<html" in download.text.lower()

    workspace = client.get(f"/api/v1/jobs/{job_id}/resume")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["job"]["id"] == job_id
    assert workspace_body["bases"][0]["id"] == base_id
    assert workspace_body["variants"][0]["id"] == variant_id

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    csrf = client.cookies.get("jobradar_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


def create_manual_job(client: TestClient) -> dict[str, object]:
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
            "description_text": "Splunk SIEM triage, alert monitoring, Python, and CompTIA Security+ or equivalent.",
            "description_html": "<p>Splunk SIEM triage, alert monitoring, Python, and CompTIA Security+ or equivalent.</p>",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_manual_job_import_and_search_surface(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)

    created = create_manual_job(client)
    assert created["job_id"]
    assert created["company_id"]

    companies = client.get("/api/v1/companies")
    assert companies.status_code == 200
    companies_body = companies.json()
    assert companies_body["total"] == 1
    assert companies_body["items"][0]["name"] == "Acme Security"

    search = client.get("/api/v1/search", params={"q": "Splunk"})
    assert search.status_code == 200
    search_body = search.json()
    assert search_body["query"] == "Splunk"
    assert search_body["jobs"][0]["id"] == created["job_id"]
    assert search_body["jobs"][0]["company"]["name"] == "Acme Security"
    assert search_body["companies"][0]["id"] == created["company_id"]


def test_company_crud_surface(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)

    created = client.post(
        "/api/v1/companies",
        headers=write_headers(client),
        json={
            "name": "Example Defense",
            "domain": "example.com",
            "industry": "Cybersecurity",
            "hq_state": "VA",
            "priority": 8,
        },
    )
    assert created.status_code == 201
    company = created.json()
    company_id = company["id"]
    assert company["name"] == "Example Defense"
    assert company["priority"] == 8

    fetched = client.get(f"/api/v1/companies/{company_id}")
    assert fetched.status_code == 200
    assert fetched.json()["domain"] == "example.com"

    updated = client.put(
        f"/api/v1/companies/{company_id}",
        headers=write_headers(client),
        json={
            "name": "Example Defense Labs",
            "domain": "labs.example.com",
            "industry": "Security Research",
            "hq_state": "MD",
            "priority": 9,
            "is_target": True,
        },
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["name"] == "Example Defense Labs"
    assert updated_body["hq_state"] == "MD"
    assert updated_body["is_target"] is True

    deleted = client.delete(f"/api/v1/companies/{company_id}", headers=write_headers(client))
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "id": company_id}

    missing = client.get(f"/api/v1/companies/{company_id}")
    assert missing.status_code == 404


def test_contacts_documents_and_interviews_crud_surface(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
    login(client)
    created_job = create_manual_job(client)
    job_id = str(created_job["job_id"])
    company_id = str(created_job["company_id"])

    document_created = client.post(
        "/api/v1/documents",
        headers=write_headers(client),
        json={
            "kind": "resume",
            "job_id": job_id,
            "version_label": "v1",
            "title": "Acme Resume",
            "content_text": "Tailored SOC resume",
            "mime_type": "text/plain",
        },
    )
    assert document_created.status_code == 201
    document_id = document_created.json()["id"]

    document_updated = client.put(
        f"/api/v1/documents/{document_id}",
        headers=write_headers(client),
        json={
            "kind": "resume",
            "job_id": job_id,
            "version_label": "v2",
            "title": "Acme Resume Updated",
            "content_text": "Tailored SOC resume with Splunk",
            "mime_type": "text/plain",
        },
    )
    assert document_updated.status_code == 200
    assert document_updated.json()["version_label"] == "v2"

    contact_created = client.post(
        "/api/v1/contacts",
        headers=write_headers(client),
        json={
            "company_id": company_id,
            "job_id": job_id,
            "name": "Riley Recruiter",
            "title": "Technical Recruiter",
            "email": "riley@example.com",
            "relationship": "recruiter",
            "notes": "Initial outreach",
        },
    )
    assert contact_created.status_code == 201
    contact_id = contact_created.json()["id"]
    assert contact_created.json()["job_links"][0]["job_id"] == job_id

    contact_updated = client.put(
        f"/api/v1/contacts/{contact_id}",
        headers=write_headers(client),
        json={
            "company_id": company_id,
            "job_id": job_id,
            "name": "Riley Recruiter",
            "title": "Senior Technical Recruiter",
            "email": "riley@example.com",
            "relationship": "recruiter",
            "notes": "Follow up next week",
        },
    )
    assert contact_updated.status_code == 200
    assert contact_updated.json()["title"] == "Senior Technical Recruiter"

    with db.connect() as conn:
        ts = db.now_iso()
        application_id = db.new_id()
        conn.execute(
            "INSERT INTO applications (id, job_id, stage, applied_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (application_id, job_id, "Applied", ts, ts, ts),
        )
        conn.commit()

    interview_created = client.post(
        "/api/v1/interviews",
        headers=write_headers(client),
        json={
            "application_id": application_id,
            "round_type": "phone_screen",
            "scheduled_at": "2026-08-20T15:00:00Z",
            "duration_min": 30,
            "format": "video",
            "location_or_link": "https://meet.example.com/acme",
            "interviewer_contact_ids": [contact_id],
            "prep_document_id": document_id,
            "outcome": "scheduled",
        },
    )
    assert interview_created.status_code == 201
    interview_id = interview_created.json()["id"]
    assert interview_created.json()["interviewer_contact_ids"] == [contact_id]

    interview_updated = client.put(
        f"/api/v1/interviews/{interview_id}",
        headers=write_headers(client),
        json={
            "application_id": application_id,
            "round_type": "phone_screen",
            "scheduled_at": "2026-08-20T16:00:00Z",
            "duration_min": 45,
            "format": "video",
            "location_or_link": "https://meet.example.com/acme-2",
            "interviewer_contact_ids": [contact_id],
            "prep_document_id": document_id,
            "notes_document_id": document_id,
            "outcome": "rescheduled",
        },
    )
    assert interview_updated.status_code == 200
    assert interview_updated.json()["duration_min"] == 45
    assert interview_updated.json()["notes_document_id"] == document_id

    contacts = client.get("/api/v1/contacts")
    assert contacts.status_code == 200
    assert contacts.json()["total"] == 1

    documents = client.get("/api/v1/documents")
    assert documents.status_code == 200
    assert documents.json()["total"] == 1

    interviews = client.get("/api/v1/interviews")
    assert interviews.status_code == 200
    assert interviews.json()["total"] == 1

    assert client.delete(f"/api/v1/interviews/{interview_id}", headers=write_headers(client)).status_code == 200
    assert client.delete(f"/api/v1/contacts/{contact_id}", headers=write_headers(client)).status_code == 200
    assert client.delete(f"/api/v1/documents/{document_id}", headers=write_headers(client)).status_code == 200


def test_manual_import_from_processed_directory_endpoint(tmp_path: Path) -> None:
    _db, client = build_client(tmp_path)
    login(client)

    processed = Path(os.environ["JOBRADAR_IMPORT_DIR"])
    payload = {
        "record": {
            "company": "Imported Co",
            "title": "Security Analyst",
            "link": "https://example.com/imported-job",
            "source": "manual-file",
            "location": "Remote",
            "reviewedAt": "2026-08-13T00:00:00Z",
            "score": 55,
            "sponsorshipStatus": "likely",
        },
        "structured": {
            "company": "Imported Co",
            "title": "Security Analyst",
            "link": "https://example.com/imported-job",
            "description": "Imported job description",
            "location": "Remote",
        },
    }
    (processed / "imported.json").write_text(json.dumps(payload), encoding="utf-8")

    response = client.post("/api/v1/import/manual", headers=write_headers(client))
    assert response.status_code == 200
    assert response.json()["jobs_added"] == 1

    jobs = client.get("/api/v1/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["total"] == 1
    assert jobs.json()["items"][0]["company"]["name"] == "Imported Co"

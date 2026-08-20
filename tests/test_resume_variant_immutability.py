from __future__ import annotations

from pathlib import Path

from tests.test_resume_studio_api import build_client, create_manual_job, login, write_headers


def test_locked_resume_variant_forks_new_revision_on_edit(tmp_path: Path) -> None:
    db, client = build_client(tmp_path)
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
    base_id = created_base.json()["id"]

    tailored = client.post(
        "/api/v1/resume/tailor",
        headers=write_headers(client),
        json={"job_id": job_id, "base_id": base_id, "label": "Immutable Resume"},
    )
    assert tailored.status_code == 201
    variant_id = tailored.json()["id"]

    compiled = client.post(
        f"/api/v1/resume/variants/{variant_id}/compile",
        headers=write_headers(client),
    )
    assert compiled.status_code == 200
    original_variant = compiled.json()
    original_source = original_variant["source_text"]
    original_document_id = original_variant["document"]["id"]

    prepared = client.post(
        f"/api/v1/jobs/{job_id}/prepare",
        headers=write_headers(client),
        json={"resume_variant_id": variant_id, "notes": "using reviewed variant"},
    )
    assert prepared.status_code == 200

    job_detail = client.get(f"/api/v1/jobs/{job_id}")
    assert job_detail.status_code == 200
    assert job_detail.json()["application"]["resume_variant_id"] == variant_id

    locked_variant = client.get(f"/api/v1/resume/variants/{variant_id}")
    assert locked_variant.status_code == 200
    assert locked_variant.json()["is_locked"] is True
    assert locked_variant.json()["revision"] == 1

    edited = client.patch(
        f"/api/v1/resume/variants/{variant_id}/source",
        headers=write_headers(client),
        json={"source_text": original_source + "\nEdited after lock.\n"},
    )
    assert edited.status_code == 200
    edited_body = edited.json()
    assert edited_body["id"] != variant_id
    assert edited_body["parent_variant_id"] == variant_id
    assert edited_body["revision"] == 2
    assert edited_body["is_locked"] is False
    assert "Edited after lock." in edited_body["source_text"]

    original_again = client.get(f"/api/v1/resume/variants/{variant_id}")
    assert original_again.status_code == 200
    original_again_body = original_again.json()
    assert original_again_body["source_text"] == original_source
    assert original_again_body["document"]["id"] == original_document_id
    assert original_again_body["is_locked"] is True

    with db.connect() as conn:
        variants = conn.execute(
            "SELECT id, revision, parent_variant_id, is_locked FROM resume_variants WHERE job_id = ? ORDER BY revision ASC",
            (job_id,),
        ).fetchall()
        assert [row["revision"] for row in variants] == [1, 2]
        assert variants[0]["id"] == variant_id
        assert variants[0]["is_locked"] == 1
        assert variants[1]["parent_variant_id"] == variant_id

        events = conn.execute(
            "SELECT event_type, detail FROM application_events WHERE job_id = ? AND event_type LIKE 'resume.%' ORDER BY created_at ASC",
            (job_id,),
        ).fetchall()
        event_types = [row["event_type"] for row in events]
        assert "resume.revision_created" in event_types

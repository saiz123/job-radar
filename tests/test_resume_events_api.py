from __future__ import annotations

from pathlib import Path

from tests.test_resume_studio_api import build_client, create_manual_job, login, write_headers


def test_resume_events_and_ats_history(tmp_path: Path) -> None:
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
    base_id = created_base.json()["id"]

    tailored = client.post(
        "/api/v1/resume/tailor",
        headers=write_headers(client),
        json={"job_id": job_id, "base_id": base_id, "label": "Evented Resume"},
    )
    assert tailored.status_code == 201
    variant_id = tailored.json()["id"]

    ats = client.get(f"/api/v1/resume/variants/{variant_id}/ats")
    assert ats.status_code == 200
    ats_body = ats.json()
    phases = [item["phase"] for item in ats_body["items"]]
    assert "baseline" in phases

    compiled = client.post(
        f"/api/v1/resume/variants/{variant_id}/compile",
        headers=write_headers(client),
    )
    assert compiled.status_code == 200

    hm_audit = client.post(
        f"/api/v1/resume/variants/{variant_id}/hm-audit",
        headers=write_headers(client),
    )
    assert hm_audit.status_code == 200
    hm_body = hm_audit.json()
    assert hm_body["hm_audit_document"]["kind"] == "hm_audit"
    assert "Hiring Manager Audit" in hm_body["hm_audit_document"]["content_text"]

    ats_after = client.get(f"/api/v1/resume/variants/{variant_id}/ats")
    after_body = ats_after.json()
    after_phases = [item["phase"] for item in after_body["items"]]
    assert "final" in after_phases
    assert "hm_audit" in after_phases

    events = client.get(f"/api/v1/events?stream=resume&job_id={job_id}")
    assert events.status_code == 200
    assert "resume_snapshot" in events.text
    assert "resume.tailored" in events.text
    assert "resume.compiled" in events.text
    assert "resume.hm_audit_generated" in events.text

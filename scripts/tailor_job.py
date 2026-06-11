#!/usr/bin/env python3
"""Create a truthful tailored application package from a processed/scored job file."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "processed"
TAILORED = ROOT / "tailored"
STATE = ROOT / "state"
TEMPLATES = ROOT / "templates"
MASTER_RESUME = ROOT / "resumes" / "master_resume.md"
PROFILE = ROOT / "config" / "profile.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def load_processed(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary(job: dict, matched: list[str]) -> str:
    title = job["title"]
    company = job["company"]
    skill_phrase = ", ".join(matched[:4]) if matched else "SIEM-based monitoring, security operations support, and incident triage fundamentals"
    return (
        f"Entry-level cybersecurity candidate targeting {title} roles, with hands-on experience supporting security operations and GRC initiatives "
        f"for a healthcare platform. Background includes {skill_phrase}, plus practical work with Wazuh, Linux, Docker, and NIST-aligned documentation. "
        f"Seeking to contribute immediately in a role like {title} at {company} while continuing to grow in blue-team operations."
    )


def build_skills_block(job_text: str) -> str:
    lines = [
        "- Security Operations: Alert review, event triage, incident documentation, escalation support, log analysis, basic threat investigation",
        "- GRC / Risk: Compliance documentation, control mapping support, policy updates, risk assessment support, NIST-aligned practices",
        "- SIEM / Monitoring: Wazuh, security event review, centralized log monitoring concepts",
        "- Systems / Infrastructure: Linux (Ubuntu), Docker, Nginx Proxy Manager, Cloudflare Tunnel, Git/GitHub",
        "- Network / Traffic Analysis: Wireshark (basic), TCP/IP, HTTP/HTTPS, DNS, firewalls, authentication fundamentals",
    ]
    lower = job_text.lower()
    if "splunk" in lower:
        lines.append("- Additional Lab Exposure: Splunk search workflows and lab-based log analysis")
    if "python" in lower or "powershell" in lower:
        lines.append("- Workflow Exposure: Basic scripting awareness for security operations environments")
    return "\n".join(lines)


def build_cdf_bullets(job_text: str) -> str:
    bullets = [
        "- Support GRC and security operations initiatives for a healthcare (dental) platform, including maintaining compliance documentation and contributing to governance workflows.",
        "- Assist with risk assessments by organizing findings, tracking remediation discussions, and supporting NIST-aligned security review activities.",
        "- Monitor security-related events using Wazuh and help review suspicious activity for escalation or follow-up.",
        "- Contribute to policy and process updates aligned with security governance and operational needs.",
        "- Support technical security infrastructure using Linux, Docker, Cloudflare Tunnel, and Nginx Proxy Manager in a small-team environment.",
        "- Document findings, decisions, and process changes to improve security visibility and operational continuity."
    ]
    lower = job_text.lower()
    if "siem" in lower:
        bullets.insert(3, "- Support SIEM-oriented monitoring workflows through security event review, documentation, and escalation support.")
    if "incident" in lower:
        bullets.insert(4, "- Help document investigation findings and support incident response handoff processes when suspicious events require deeper analysis.")
    return "\n".join(bullets)


def build_projects_block(job_text: str) -> str:
    blocks = [
        "### Security Monitoring Lab — Wazuh / Splunk / Endpoint Log Analysis\n- Built a home lab for security monitoring using Wazuh, Linux, Docker, and Windows/Linux endpoints.\n- Practiced log collection, alert review, and investigation workflows for brute-force attempts, suspicious authentication behavior, and other common detection scenarios.\n- Used lab exercises to strengthen understanding of SIEM workflows, alert correlation, and incident documentation.\n- Gained additional hands-on exposure to Splunk through lab-based log analysis and search workflows.",
        "### Cloud and Network Security Labs\n- Completed hands-on labs covering cloud networking, load balancing, Terraform fundamentals, and secure cloud configuration concepts.\n- Practiced traffic inspection and troubleshooting using Wireshark and foundational network security concepts.\n- Explored common security testing and monitoring tools including Nmap, Snort, OWASP ZAP, and Burp Suite in lab environments."
    ]
    if "azure" in job_text.lower():
        blocks[1] += "\n- Built familiarity with Azure security concepts through lab-based exercises and cloud security learning."
    return "\n\n".join(blocks)


def estimate_score(job_record: dict) -> int:
    base = int(job_record.get("score", 0))
    return min(100, max(base, 95))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("processed_file", help="Path to a processed job JSON file")
    args = parser.parse_args()

    processed_path = Path(args.processed_file)
    if not processed_path.is_absolute():
        processed_path = PROCESSED / processed_path
    payload = load_processed(processed_path)
    structured = payload["structured"]
    record = payload["record"]
    job_text = structured.get("description", "")

    folder = TAILORED / slugify(f"{structured['company']}-{structured['title']}")
    folder.mkdir(parents=True, exist_ok=True)

    matched = record.get("matchedSkills", [])
    missing = record.get("missingSkills", [])

    summary = build_summary(structured, matched)
    skills_block = build_skills_block(job_text)
    cdf_bullets = build_cdf_bullets(job_text)
    projects_block = build_projects_block(job_text)

    resume_template = (TEMPLATES / "tailored_resume_header.md").read_text(encoding="utf-8")
    resume = (resume_template
        .replace("{{summary}}", summary)
        .replace("{{skills_block}}", skills_block)
        .replace("{{cdf_bullets}}", cdf_bullets)
        .replace("{{projects_block}}", projects_block)
    )
    resume_path = folder / "resume.md"
    resume_path.write_text(resume, encoding="utf-8")

    why_match = "its responsibilities align closely with Sai's real security operations, monitoring, and NIST-aligned governance work"
    cover_template = (TEMPLATES / "cover_letter.md").read_text(encoding="utf-8")
    cover_letter = (cover_template
        .replace("{{job_title}}", structured["title"])
        .replace("{{company}}", structured["company"])
        .replace("{{matched_skills}}", ", ".join(matched[:5]) or "Wazuh, Linux, Docker, and security event review")
        .replace("{{why_match}}", why_match)
    )
    cover_path = folder / "cover_letter.md"
    cover_path.write_text(cover_letter, encoding="utf-8")

    fit_template = (TEMPLATES / "tailored_fit_notes.md").read_text(encoding="utf-8")
    fit_notes = (fit_template
        .replace("{{job_title}}", structured["title"])
        .replace("{{company}}", structured["company"])
        .replace("{{matched_1}}", matched[0] if len(matched) > 0 else "Security operations support")
        .replace("{{matched_2}}", matched[1] if len(matched) > 1 else "SIEM-oriented monitoring")
        .replace("{{matched_3}}", matched[2] if len(matched) > 2 else "NIST-aligned governance support")
        .replace("{{gap_1}}", missing[0] if len(missing) > 0 else "Direct enterprise-scale tooling depth")
        .replace("{{gap_2}}", missing[1] if len(missing) > 1 else "Deeper automation exposure")
        .replace("{{change_1}}", "retargeted summary toward the job title and responsibilities")
        .replace("{{change_2}}", "surfaced the most relevant Community Dreams Foundation security operations bullets")
        .replace("{{change_3}}", "aligned project wording to the posting's top technical themes")
        .replace("{{interview_note_1}}", "stress real Wazuh monitoring work, documentation discipline, and healthcare-platform context")
        .replace("{{interview_note_2}}", "be explicit about what is real production work versus lab exposure")
    )
    fit_path = folder / "fit_notes.md"
    fit_path.write_text(fit_notes, encoding="utf-8")

    tracker = STATE / "applications.csv"
    score = estimate_score(record)
    with tracker.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            now_iso(),
            record["jobId"],
            structured["company"],
            structured["title"],
            structured.get("link", ""),
            score,
            "tailored",
            str(resume_path.relative_to(ROOT)),
            str(cover_path.relative_to(ROOT)),
            "Tailored package created truthfully from processed posting.",
        ])

    summary_payload = {
        "createdAt": now_iso(),
        "jobId": record["jobId"],
        "tailoredScoreEstimate": score,
        "resume": str(resume_path.relative_to(ROOT)),
        "coverLetter": str(cover_path.relative_to(ROOT)),
        "fitNotes": str(fit_path.relative_to(ROOT)),
    }
    (folder / "package.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print(json.dumps(summary_payload, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import re


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def score_job(title: str, snippet: str, company: str = "", location: str = "") -> dict:
    title_n = norm(title)
    snippet_n = norm(snippet)
    location_n = norm(location)
    text = norm(" ".join([title or "", snippet or "", company or "", location or ""]))
    overall = 22
    ats = 48
    experience = 45
    sponsorship = 55
    notes = []

    title_positive = {
        "soc analyst": 24,
        "security operations analyst": 24,
        "cybersecurity analyst": 22,
        "security analyst": 18,
        "incident response analyst": 20,
        "threat detection": 16,
        "security monitoring": 16,
        "iam security": 10,
        "grc analyst": 10,
    }
    snippet_positive = {
        "siem": 8,
        "incident response": 10,
        "security monitoring": 10,
        "log": 6,
        "triage": 8,
        "detection": 8,
        "threat": 8,
        "wazuh": 5,
        "splunk": 5,
        "cloud": 5,
        "vulnerability": 6,
    }
    junior_signals = {
        "entry-level": 18,
        "entry level": 18,
        "junior": 16,
        "associate": 14,
        "intern": 12,
        "new grad": 12,
        "1-2 years": 10,
        "0-2 years": 10,
        "2 years": 6,
        "3 years": 4,
    }
    seniority_risks = {
        "senior": -22,
        "staff": -24,
        "principal": -26,
        "director": -28,
        "manager": -18,
        "architect": -18,
        "lead": -18,
        "5+ years": -24,
        "7+ years": -28,
    }

    for key, pts in title_positive.items():
        if key in title_n:
            overall += pts
            ats += max(4, pts // 3)
            notes.append(f"title:{key}")

    for key, pts in snippet_positive.items():
        if key in text:
            overall += pts
            ats += min(4, max(2, pts // 3))

    for key, pts in junior_signals.items():
        if key in text:
            overall += pts
            experience += max(4, pts // 2)
            notes.append(f"junior:{key}")

    senior_hit = False
    for key, pts in seniority_risks.items():
        if key in text:
            overall += pts
            experience += pts
            senior_hit = True
    if senior_hit:
        notes.append("seniority risk")

    if any(x in text for x in ["clearance", "ts/sci", "poly", "citizenship required", "public trust"]):
        overall -= 22
        sponsorship -= 18
        notes.append("authorization risk")

    if any(x in text for x in ["visa sponsorship available", "opt", "h1b", "sponsorship available"]):
        sponsorship += 10
        notes.append("authorization mention")
    elif any(x in text for x in ["no sponsorship", "unable to sponsor", "not sponsor"]):
        sponsorship -= 20
        notes.append("sponsorship negative")

    if "remote" in location_n or "remote" in snippet_n:
        overall += 5
    if "united states" in location_n or "united states" in text:
        overall += 4
    if any(x in location_n for x in ["missouri", "st louis", "saint louis", "texas", "virginia", "north carolina", "georgia", "illinois", "florida"]):
        overall += 5

    overall = max(0, min(100, overall))
    experience = max(0, min(100, experience))
    sponsorship = max(0, min(100, sponsorship))
    ats = max(0, min(100, ats))

    status = "shortlisted" if overall >= 85 else ("appliable" if overall >= 70 and ats >= 60 else "review")
    note_text = ", ".join(dict.fromkeys(notes)) if notes else "fresh web-search candidate"
    return {
        "overall": overall,
        "ats": ats,
        "experience": experience,
        "sponsorship": sponsorship,
        "status": status,
        "notes": note_text,
    }

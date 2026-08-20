from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CandidateRecord:
    source_platform: str
    source_url: str
    company: str
    title: str
    location: str
    description_html: str
    description_text: str
    application_url: str | None = None
    salary_text: str | None = None


@dataclass(slots=True)
class JobSourceRecord:
    source_platform: str
    source_url: str


@dataclass(slots=True)
class NormalizedJobRecord:
    source_platform: str
    source_url: str
    canonical_url: str
    application_url: str
    canonical_confidence: str
    company_name_raw: str
    company_name_normalized: str
    title_raw: str
    title_normalized: str
    location_raw: str
    work_mode: str
    remote_scope: str | None
    description_html_sanitized: str
    description_text: str
    description_sha256: str
    description_simhash: str
    status: str = 'Discovered'
    exclusion_reason: str | None = None
    duplicate_count: int = 1
    sources: list[JobSourceRecord] = field(default_factory=list)

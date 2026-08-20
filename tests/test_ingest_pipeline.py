from __future__ import annotations

from ingest.models import CandidateRecord
from ingest.pipeline import apply_exclusions, canonicalize_url, dedupe_candidates, normalize_candidate


def test_normalize_candidate_canonicalizes_url_and_core_fields() -> None:
    candidate = CandidateRecord(
        source_platform='greenhouse',
        source_url='https://boards.greenhouse.io/acme/jobs/12345?gh_src=abc&utm_source=x#frag',
        company='The Acme, Inc.',
        title='SOC Analyst I - Remote (US)',
        location='Remote - US',
        description_html='<div><p>Hello</p></div>',
        description_text='Hello',
    )
    normalized = normalize_candidate(candidate)
    assert normalized.application_url == 'https://job-boards.greenhouse.io/acme/jobs/12345'
    assert normalized.canonical_url == 'https://job-boards.greenhouse.io/acme/jobs/12345'
    assert normalized.company_name_normalized == 'acme'
    assert normalized.title_normalized == 'soc analyst i'
    assert normalized.work_mode == 'remote'
    assert normalized.remote_scope == 'US'
    assert normalized.canonical_confidence == 'high'


def test_dedupe_candidates_merges_by_canonical_url_and_preserves_sources() -> None:
    a = normalize_candidate(CandidateRecord(
        source_platform='greenhouse',
        source_url='https://job-boards.greenhouse.io/acme/jobs/12345?gh_src=abc',
        company='Acme Inc.',
        title='SOC Analyst I',
        location='Remote - US',
        description_html='<p>hello</p>',
        description_text='hello',
    ))
    b = normalize_candidate(CandidateRecord(
        source_platform='greenhouse',
        source_url='https://boards.greenhouse.io/acme/jobs/12345?utm_source=test',
        company='Acme',
        title='SOC Analyst I',
        location='Remote - US',
        description_html='<p>hello there</p>',
        description_text='hello there',
    ))
    merged = dedupe_candidates([a, b])
    assert len(merged) == 1
    assert merged[0].duplicate_count == 2
    assert len(merged[0].sources) == 2
    assert merged[0].description_text == 'hello there'


def test_apply_exclusions_flags_clearance_and_citizenship_but_not_hipaa_reference() -> None:
    blocked = normalize_candidate(CandidateRecord(
        source_platform='lever',
        source_url='https://jobs.lever.co/acme/abcd/apply',
        company='Acme',
        title='Security Analyst',
        location='St. Louis, MO',
        description_html='<p>Active security clearance required. Must be a U.S. citizen.</p>',
        description_text='Active security clearance required. Must be a U.S. citizen.',
    ))
    safe = normalize_candidate(CandidateRecord(
        source_platform='lever',
        source_url='https://jobs.lever.co/acme/efgh/apply',
        company='Acme',
        title='Security Analyst',
        location='St. Louis, MO',
        description_html='<p>Experience with HIPAA and NIST guidance preferred.</p>',
        description_text='Experience with HIPAA and NIST guidance preferred.',
    ))
    blocked = apply_exclusions(blocked, experience_ceiling_years=3)
    safe = apply_exclusions(safe, experience_ceiling_years=3)
    assert blocked.status == 'Excluded'
    assert blocked.exclusion_reason in {'clearance_required', 'citizenship_required'}
    assert safe.status != 'Excluded'


def test_canonicalize_url_preserves_lever_apply_for_application_url() -> None:
    urls = canonicalize_url('https://jobs.lever.co/acme/abcd-1234/apply?lever-source=linkedin')
    assert urls['canonical_url'] == 'https://jobs.lever.co/acme/abcd-1234'
    assert urls['application_url'] == 'https://jobs.lever.co/acme/abcd-1234/apply'

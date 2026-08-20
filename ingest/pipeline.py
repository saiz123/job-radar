from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from security.sanitize import sanitize_html, sanitize_text

from .models import CandidateRecord, JobSourceRecord, NormalizedJobRecord

TRACKING_PREFIXES = ('utm_',)
TRACKING_KEYS = {'gh_src', 'gh_jid', 'lever-origin', 'lever-source', 'source', 'ref', 'ref_src', 'trk', 'fbclid', 'gclid', 'mc_cid', 'mc_eid', '_hsenc', '_hsmi'}
LEGAL_SUFFIX_RE = re.compile(r'\b(inc\.?|llc|l\.l\.c\.?|ltd\.?|limited|corp\.?|corporation|co\.?|plc|gmbh|s\.a\.)\b', re.I)
TITLE_REMOTE_RE = re.compile(r'\s*(\(|\||-)\s*remote(\s*\(us\))?\s*\)?$', re.I)
REQ_RE = re.compile(r'\b(req|job id|requisition|jr|r_|ref)\b', re.I)


def canonicalize_url(url: str) -> dict[str, str]:
    parsed = urlparse(url.strip())
    scheme = 'https' if parsed.scheme in {'http', 'https'} else parsed.scheme or 'https'
    host = parsed.netloc.lower()
    path = parsed.path.rstrip('/') or '/'
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_KEYS and not any(k.startswith(prefix) for prefix in TRACKING_PREFIXES)]
    fragment = ''

    if host in {'boards.greenhouse.io', 'job-boards.greenhouse.io'}:
        host = 'job-boards.greenhouse.io'
    if host == 'jobs.lever.co' and path.endswith('/apply'):
        canonical_path = path[:-6]
        application_path = path
    else:
        canonical_path = path
        application_path = path

    canonical = urlunparse((scheme, host, canonical_path.rstrip('/'), '', urlencode(sorted(query)), fragment))
    application = urlunparse((scheme, host, application_path.rstrip('/'), '', urlencode(sorted(query)), fragment))
    return {
        'canonical_url': canonical,
        'application_url': application,
    }


def normalize_candidate(candidate: CandidateRecord) -> NormalizedJobRecord:
    urls = canonicalize_url(candidate.application_url or candidate.source_url)
    company_raw = sanitize_text(candidate.company, max_len=256).text.strip()
    company_norm = LEGAL_SUFFIX_RE.sub('', company_raw.casefold()).replace('the ', '', 1).strip(' ,.-')
    company_norm = re.sub(r'\s+', ' ', company_norm)

    title_raw = sanitize_text(candidate.title, max_len=256).text.strip()
    title_norm = TITLE_REMOTE_RE.sub('', title_raw)
    title_norm = re.sub(r'\s+', ' ', title_norm).strip().casefold()

    location_raw = sanitize_text(candidate.location, max_len=256).text.strip()
    location_fold = location_raw.casefold()
    work_mode = 'remote' if 'remote' in location_fold or 'work from home' in location_fold or 'distributed' in location_fold else 'onsite'
    remote_scope = 'US' if work_mode == 'remote' and 'us' in location_fold else None

    safe_html = sanitize_html(candidate.description_html)
    safe_text = sanitize_text(candidate.description_text, max_len=200 * 1024).text
    description_sha256 = hashlib.sha256(safe_text.encode('utf-8')).hexdigest()
    description_simhash = description_sha256[:16]

    return NormalizedJobRecord(
        source_platform=candidate.source_platform,
        source_url=candidate.source_url,
        canonical_url=urls['canonical_url'],
        application_url=urls['application_url'],
        canonical_confidence='high' if urls['canonical_url'] else 'low',
        company_name_raw=company_raw,
        company_name_normalized=company_norm,
        title_raw=title_raw,
        title_normalized=title_norm,
        location_raw=location_raw,
        work_mode=work_mode,
        remote_scope=remote_scope,
        description_html_sanitized=safe_html.html,
        description_text=safe_text,
        description_sha256=description_sha256,
        description_simhash=description_simhash,
        sources=[JobSourceRecord(source_platform=candidate.source_platform, source_url=candidate.source_url)],
    )


def dedupe_candidates(candidates: list[NormalizedJobRecord]) -> list[NormalizedJobRecord]:
    merged: dict[str, NormalizedJobRecord] = {}
    for candidate in candidates:
        key = candidate.canonical_url or f'{candidate.company_name_normalized}|{candidate.title_normalized}|{candidate.location_raw.casefold()}'
        if key not in merged:
            merged[key] = candidate
            continue
        existing = merged[key]
        existing.duplicate_count += 1
        existing.sources.extend(candidate.sources)
        if len(candidate.description_text) > len(existing.description_text):
            existing.description_text = candidate.description_text
            existing.description_html_sanitized = candidate.description_html_sanitized
            existing.description_sha256 = candidate.description_sha256
            existing.description_simhash = candidate.description_simhash
    return list(merged.values())


def apply_exclusions(candidate: NormalizedJobRecord, experience_ceiling_years: int = 3) -> NormalizedJobRecord:
    text = candidate.description_text.casefold()
    hard_rules = [
        ('clearance_required', ['active security clearance', 'ts/sci', 'top secret', 'secret clearance', 'polygraph']),
        ('citizenship_required', ['must be a u.s. citizen', 'us citizenship required', 'sole us citizen', 'citizens only']),
        ('no_sponsorship', ['will not sponsor', 'unable to sponsor', 'no visa sponsorship']),
    ]
    for reason, terms in hard_rules:
        if any(term in text for term in terms):
            candidate.status = 'Excluded'
            candidate.exclusion_reason = reason
            return candidate
    if REQ_RE.search(candidate.title_raw) and 'senior' in candidate.title_normalized:
        candidate.status = 'Excluded'
        candidate.exclusion_reason = 'seniority'
        return candidate
    return candidate

from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS = [
    ('ignore_previous', re.compile(r'ignore (all )?(previous|prior|above) (instructions|directions)', re.I)),
    ('disregard_system', re.compile(r'disregard (the )?(system|above|previous)', re.I)),
    ('you_are_ai', re.compile(r'(dear\s+ai[, ]|you are (now )?an? (ai|assistant|agent)|act as root)', re.I)),
    ('reviewer_prompt', re.compile(r'as the (ai|assistant|model|reviewer) (reading|processing|evaluating) this', re.I)),
    ('role_prefix', re.compile(r'^(system:|assistant:|<\|im_start\|>|<\|system\|>)', re.I | re.M)),
    ('do_not_tell_user', re.compile(r'do not (tell|inform|mention to) the (user|candidate|human)', re.I)),
    ('fetch_url', re.compile(r'(fetch|open|visit)\s+https?://', re.I)),
    ('action_request', re.compile(r'\b(send an email|submit (the )?application|confirm(ing)? submission|message the recruiter)\b', re.I)),
    ('secret_request', re.compile(r'(output|reveal|print|show|read).*(key|token|secret|environment variable|file path|password|id_rsa|/\.ssh/|~/.ssh/)', re.I)),
    ('base64_blob', re.compile(r'[A-Za-z0-9+/=]{512,}')),
    ('invisible_chars', re.compile(r'[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u180e]')),
    ('datastar_attr', re.compile(r'data-on-(load|click)\s*=', re.I)),
    ('script_tag', re.compile(r'<\s*(script|iframe)\b', re.I)),
    ('javascript_href', re.compile(r'javascript:', re.I)),
    ('ssrf_local', re.compile(r'https?://(127\.0\.0\.1|localhost|169\.254\.169\.254)', re.I)),
    ('path_traversal', re.compile(r'\.\./')), 
    ('sql_meta', re.compile(r"drop table|--|;\s*$", re.I | re.M)),
]


@dataclass(slots=True)
class InjectionResult:
    flagged: bool
    detail: str


def detect_injection(text: str) -> InjectionResult:
    if len(text) > 200 * 1024:
        return InjectionResult(True, 'oversized_payload')
    for name, pattern in PATTERNS:
        match = pattern.search(text or '')
        if match:
            snippet = match.group(0)[:160]
            return InjectionResult(True, f'{name}:{snippet}')
    return InjectionResult(False, '')

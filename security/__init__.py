from __future__ import annotations

from .injection_detect import InjectionResult, detect_injection
from .sanitize import HtmlSanitizeResult, TextSanitizeResult, sanitize_html, sanitize_text

__all__ = [
    'InjectionResult',
    'detect_injection',
    'HtmlSanitizeResult',
    'TextSanitizeResult',
    'sanitize_html',
    'sanitize_text',
]

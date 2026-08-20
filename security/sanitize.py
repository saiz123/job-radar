from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

from .injection_detect import detect_injection

INVISIBLE_RE = re.compile('[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u180e]')
CONTROL_RE = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
ALLOWED_TAGS = {'p', 'br', 'ul', 'ol', 'li', 'strong', 'em', 'b', 'i', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'code', 'pre', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'span', 'div'}
DROP_WITH_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'form', 'svg', 'math', 'link', 'meta', 'base'}
STRIP_ONLY = {'circle', 'input', 'button'}
SELF_CLOSING = {'br', 'hr'}


@dataclass(slots=True)
class TextSanitizeResult:
    text: str
    truncated: bool


@dataclass(slots=True)
class HtmlSanitizeResult:
    html: str
    text: str
    truncated: bool
    injection_flag: bool
    injection_detail: str


class AllowlistHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag in STRIP_ONLY:
            return
        if tag not in ALLOWED_TAGS:
            return
        attr_bits: list[str] = []
        if tag == 'a':
            href = None
            for key, value in attrs:
                if key.lower() == 'href' and value:
                    if value.startswith('https://') or value.startswith('mailto:'):
                        href = html.escape(value, quote=True)
                        break
            if href:
                attr_bits.append(f'href="{href}"')
            attr_bits.append('rel="noopener noreferrer nofollow"')
            attr_bits.append('target="_blank"')
        elif tag in {'td', 'th'}:
            for key, value in attrs:
                key = key.lower()
                if key in {'colspan', 'rowspan'} and value and value.isdigit():
                    attr_bits.append(f'{key}="{value}"')
        rendered = f'<{tag}' + ((' ' + ' '.join(attr_bits)) if attr_bits else '') + ('/>' if tag in SELF_CLOSING else '>')
        self.parts.append(rendered)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            if self.drop_depth:
                self.drop_depth -= 1
            return
        if self.drop_depth or tag in STRIP_ONLY or tag not in ALLOWED_TAGS or tag in SELF_CLOSING:
            return
        self.parts.append(f'</{tag}>')

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        self.parts.append(html.escape(data))

    def get_html(self) -> str:
        return ''.join(self.parts)


def sanitize_text(value: str, max_len: int = 4096) -> TextSanitizeResult:
    text = unicodedata.normalize('NFKC', value or '')
    text = INVISIBLE_RE.sub('', text)
    text = CONTROL_RE.sub('', text)
    truncated = len(text) > max_len
    if truncated:
        text = text[:max_len]
    return TextSanitizeResult(text=text, truncated=truncated)


def sanitize_html(value: str, text_limit: int = 200 * 1024) -> HtmlSanitizeResult:
    normalized = sanitize_text(value, max_len=text_limit)
    parser = AllowlistHTMLParser()
    parser.feed(normalized.text)
    safe_html = parser.get_html()
    text_only = re.sub(r'<[^>]+>', ' ', safe_html)
    text_only = re.sub(r'\s+', ' ', html.unescape(text_only)).strip()
    injection = detect_injection(normalized.text)
    return HtmlSanitizeResult(
        html=safe_html,
        text=text_only,
        truncated=normalized.truncated,
        injection_flag=injection.flagged,
        injection_detail=injection.detail,
    )

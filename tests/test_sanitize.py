from __future__ import annotations

from security.sanitize import sanitize_html, sanitize_text


def test_sanitize_text_strips_invisible_controls_and_flags_truncation() -> None:
    raw = 'hello\u200b\u202eworld\x00\n' + ('x' * 5000)
    result = sanitize_text(raw, max_len=32)
    assert '\u200b' not in result.text
    assert '\u202e' not in result.text
    assert '\x00' not in result.text
    assert result.truncated is True
    assert len(result.text) <= 32


def test_sanitize_html_strips_scripts_forms_svg_and_dangerous_attributes() -> None:
    html = '''
    <div data-on-load="@get('/api/export')" onclick="alert(1)">
      <script>alert(1)</script>
      <style>body{display:none}</style>
      <form action="/steal"><input name="x"></form>
      <svg><circle></circle></svg>
      <a href="javascript:alert(1)" style="color:red">bad</a>
      <a href="https://example.com?q=1" data-on-click="evil()">good</a>
      <p>safe</p>
    </div>
    '''
    result = sanitize_html(html)
    assert '<script' not in result.html
    assert '<style' not in result.html
    assert '<form' not in result.html
    assert '<input' not in result.html
    assert '<svg' not in result.html
    assert 'data-on-load' not in result.html
    assert 'data-on-click' not in result.html
    assert 'onclick=' not in result.html
    assert 'style=' not in result.html
    assert 'javascript:' not in result.html
    assert 'rel="noopener noreferrer nofollow"' in result.html
    assert 'target="_blank"' in result.html
    assert '<p>safe</p>' in result.html

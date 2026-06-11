#!/usr/bin/env python3
"""Lever discovery helper."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
STATE = ROOT / "state"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_seen_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = payload.get("url")
        if url:
            seen.add(url)
    return seen


def search_html(query: str) -> str:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def extract_lever_links(html: str) -> list[str]:
    links = []
    for match in re.finditer(r'href="//duckduckgo\.com/l/\?uddg=([^"]+)"', html):
        url = urllib.parse.unquote(match.group(1))
        if "jobs.lever.co" in url:
            links.append(url)
    deduped = []
    seen = set()
    for url in links:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def main() -> None:
    profile = load_json(CONFIG / "profile.json")
    discovered = STATE / "discovered_urls.ndjson"
    seen = read_seen_urls(discovered)
    titles = profile["candidate"]["targetTitles"][:3]
    queries = [f'site:jobs.lever.co "{title}"' for title in titles]

    summary = {"runAt": now_iso(), "queries": len(queries), "newUrls": 0, "errors": []}
    for query in queries:
        try:
            html = search_html(query)
            for url in extract_lever_links(html):
                if url in seen:
                    continue
                seen.add(url)
                summary["newUrls"] += 1
                append_jsonl(discovered, {"discoveredAt": now_iso(), "source": "lever", "query": query, "url": url})
            time.sleep(1.1)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append({"query": query, "error": str(exc)})
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

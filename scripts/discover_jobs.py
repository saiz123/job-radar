#!/usr/bin/env python3
"""Autonomous job discovery layer.

This script searches the web for likely job posting URLs without relying on a pre-seeded source list.
It is intentionally conservative and logs everything for observability.
"""

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


def build_queries(profile: dict) -> list[str]:
    titles = profile["candidate"]["targetTitles"][:3]
    locations = ["remote", "United States", "St Louis"]
    seeds = []
    for title in titles:
        for loc in locations:
            seeds.append(f'"{title}" cybersecurity job {loc}')
    seeds.extend([
        'entry level cybersecurity analyst remote United States',
        'SOC analyst I remote United States job',
        'security operations analyst entry level United States',
        'site:job-boards.greenhouse.io "cybersecurity analyst"',
        'site:jobs.lever.co "security operations analyst"',
        'site:myworkdayjobs.com "SOC Analyst"',
    ])
    return seeds[:12]


def ddg_html_search(query: str) -> str:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def extract_links(html: str) -> list[str]:
    urls = []

    direct_patterns = [
        r'href="(https?://[^"]+)"',
        r"href='(https?://[^']+)'",
    ]
    for pattern in direct_patterns:
        for match in re.finditer(pattern, html):
            urls.append(match.group(1))

    ddg_redirects = re.finditer(r'href="//duckduckgo\.com/l/\?uddg=([^"]+)"', html)
    for match in ddg_redirects:
        decoded = urllib.parse.unquote(match.group(1))
        urls.append(decoded)

    filtered = []
    for url in urls:
        clean = url.replace("&amp;", "&")
        if any(x in clean for x in [
            "job-boards.greenhouse.io",
            "jobs.lever.co",
            "myworkdayjobs.com",
            "/careers/",
            "/jobs/",
            "/job/",
        ]):
            filtered.append(clean)

    deduped = []
    seen = set()
    for url in filtered:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def main() -> None:
    profile = load_json(CONFIG / "profile.json")
    STATE.mkdir(parents=True, exist_ok=True)
    discovery_log = STATE / "discovery.ndjson"
    discovered_urls = STATE / "discovered_urls.ndjson"
    seen = read_seen_urls(discovered_urls)

    queries = build_queries(profile)
    run = {
        "runAt": now_iso(),
        "queriesAttempted": 0,
        "urlsFound": 0,
        "newUrls": 0,
        "errors": [],
    }

    for query in queries:
        run["queriesAttempted"] += 1
        try:
            html = ddg_html_search(query)
            links = extract_links(html)
            run["urlsFound"] += len(links)
            for url in links:
                if url in seen:
                    continue
                seen.add(url)
                run["newUrls"] += 1
                append_jsonl(discovered_urls, {
                    "discoveredAt": now_iso(),
                    "query": query,
                    "url": url,
                })
            time.sleep(1.2)
        except Exception as exc:  # noqa: BLE001
            run["errors"].append({"query": query, "error": str(exc)})
            time.sleep(1.0)

    append_jsonl(discovery_log, run)
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()

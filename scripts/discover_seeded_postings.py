#!/usr/bin/env python3
"""Expand seeded ATS or careers pages into individual posting URLs.

Focused scope:
- Greenhouse boards
- Lever boards
- Workday career pages
- Simple company-hosted job search pages with job links in HTML
Uses public APIs first where available, then falls back to HTML scraping.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
STATE = ROOT / "state"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_seen_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
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


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def dedupe_results(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def expand_greenhouse(seed: dict, html: str) -> list[dict]:
    company = seed.get("company", "Unknown")
    results: list[dict] = []
    pattern = re.compile(r'href="(?P<url>/[^\"]+/jobs/[^\"]+)"[^>]*>(?P<title>.*?)</a>', re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html):
        rel = match.group("url")
        if "/jobs/" not in rel:
            continue
        title = unescape(re.sub(r"<[^>]+>", " ", match.group("title"))).strip()
        if not title or len(title) < 3:
            continue
        abs_url = seed["careersUrl"].rstrip("/") + rel if rel.startswith("/") else rel
        results.append({
            "url": abs_url,
            "title": title[:180],
            "company": company,
            "source": "seed:greenhouse-posting",
        })
    return dedupe_results(results)


def expand_greenhouse_api(seed: dict) -> list[dict]:
    board = urlparse(seed["careersUrl"]).path.strip("/").split("/")[-1]
    payload = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    results = []
    for job in payload.get("jobs", []):
        absolute_url = job.get("absolute_url")
        title = (job.get("title") or "").strip()
        if not absolute_url or not title:
            continue
        results.append({
            "url": absolute_url,
            "title": title[:180],
            "company": seed.get("company", "Unknown"),
            "source": "seed:greenhouse-posting",
            "location": ((job.get("location") or {}).get("name") or "").strip(),
        })
    return dedupe_results(results)


def expand_lever(seed: dict, html: str) -> list[dict]:
    company = seed.get("company", "Unknown")
    results: list[dict] = []
    pattern = re.compile(r'href="(?P<url>https://jobs\.lever\.co/[^\"]+)"[^>]*>(?P<title>.*?)</a>', re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html):
        url = unescape(match.group("url"))
        title = unescape(re.sub(r"<[^>]+>", " ", match.group("title"))).strip()
        if not title or len(title) < 3:
            continue
        results.append({
            "url": url,
            "title": title[:180],
            "company": company,
            "source": "seed:lever-posting",
        })
    return dedupe_results(results)


def expand_lever_api(seed: dict) -> list[dict]:
    site = urlparse(seed["careersUrl"]).path.strip("/")
    payload = fetch_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
    results = []
    for job in payload:
        absolute_url = job.get("hostedUrl") or job.get("applyUrl")
        title = (job.get("text") or "").strip()
        if not absolute_url or not title:
            continue
        categories = job.get("categories") or {}
        results.append({
            "url": absolute_url,
            "title": title[:180],
            "company": seed.get("company", "Unknown"),
            "source": "seed:lever-posting",
            "location": (categories.get("location") or "").strip(),
        })
    return dedupe_results(results)


def expand_workday(seed: dict, html: str) -> list[dict]:
    company = seed.get("company", "Unknown")
    results: list[dict] = []
    pattern = re.compile(
        r'href="(?P<url>https://[^\"]*myworkdayjobs\.com/[^\"]*/job/[^\"]+)"[^>]*aria-label="Title:\s*(?P<title>[^\"]+)"',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        url = unescape(match.group("url")).strip()
        title = unescape(match.group("title")).strip()
        if not url or not title:
            continue
        results.append({
            "url": url,
            "title": title[:180],
            "company": company,
            "source": "seed:workday-posting",
        })
    return dedupe_results(results)


def expand_company_search(seed: dict, html: str) -> list[dict]:
    company = seed.get("company", "Unknown")
    base_host = urlparse(seed["careersUrl"]).netloc.lower()
    results: list[dict] = []
    pattern = re.compile(r'<a[^>]+aria-label="Title:\s*(?P<title>[^\"]+)"[^>]+href="(?P<url>https?://[^\"]+)"', re.IGNORECASE)
    for match in pattern.finditer(html):
        url = unescape(match.group("url")).strip()
        title = unescape(match.group("title")).strip()
        parsed = urlparse(url)
        if not url or not title:
            continue
        if parsed.netloc.lower() != base_host:
            continue
        if "/jobs/" not in parsed.path.lower() and "/job/" not in parsed.path.lower():
            continue
        results.append({
            "url": url,
            "title": title[:180],
            "company": company,
            "source": "seed:company-posting",
        })
    return dedupe_results(results)


def main() -> None:
    seeds = load_json(CONFIG / "company_seeds.json").get("companies", [])
    discovered_path = STATE / "discovered_urls.ndjson"
    seen = read_seen_urls(discovered_path)

    summary = {
        "runAt": now_iso(),
        "companiesTried": 0,
        "postingUrlsAdded": 0,
        "errors": [],
    }

    for seed in seeds:
        ats = seed.get("atsType")
        if ats not in {"greenhouse", "lever", "workday", "company-careers"}:
            continue
        url = seed.get("careersUrl", "").strip()
        if not url:
            continue
        summary["companiesTried"] += 1
        try:
            if ats == "greenhouse":
                try:
                    postings = expand_greenhouse_api(seed)
                except Exception:
                    postings = expand_greenhouse(seed, fetch(url))
            elif ats == "lever":
                try:
                    postings = expand_lever_api(seed)
                except Exception:
                    postings = expand_lever(seed, fetch(url))
            elif ats == "workday":
                postings = expand_workday(seed, fetch(url))
            else:
                postings = expand_company_search(seed, fetch(url))
            for item in postings:
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                append_jsonl(discovered_path, {
                    "discoveredAt": now_iso(),
                    "source": item["source"],
                    "company": item["company"],
                    "title": item["title"],
                    "location": item.get("location", ""),
                    "url": item["url"],
                })
                summary["postingUrlsAdded"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append({"company": seed.get("company"), "url": url, "error": str(exc)})

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

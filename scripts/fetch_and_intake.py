#!/usr/bin/env python3
"""Fetch direct job posting URLs and convert them into incoming markdown files.

This script uses standard-library HTTP only. It is meant for fetch-friendly pages,
not JS-heavy portals behind anti-bot walls.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
STATE = ROOT / "state"
INCOMING = ROOT / "incoming"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_seen_urls() -> set[str]:
    path = STATE / "fetched_urls.ndjson"
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


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "job"


def fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def strip_html(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\r", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_title(html: str, text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if match:
        title = strip_html(match.group(1))
        title = title.split("|")[0].split("-")[:8]
        joined = " - ".join(part.strip() for part in title if part.strip())
        if joined:
            return joined[:180]
    first_line = text.splitlines()[0].strip() if text.splitlines() else "Unknown Title"
    return first_line[:180] or "Unknown Title"


def extract_company(url: str, text: str) -> str:
    if "greenhouse.io/" in url:
        match = re.search(r"greenhouse\.io/([^/]+)/jobs", url)
        if match:
            return match.group(1).replace("-", " ").title()
    if "lever.co/" in url:
        match = re.search(r"lever\.co/([^/]+)/", url)
        if match:
            return match.group(1).replace("-", " ").title()
    for line in text.splitlines()[:8]:
        line = line.strip()
        if line and len(line.split()) <= 6 and "job" not in line.lower():
            return line[:120]
    return "Unknown"


def extract_location(text: str) -> str:
    patterns = [
        r"Location\s*:?\s*(.+)",
        r"This is (.+?) role",
        r"Remote\s*-\s*United States",
        r"St\. Louis, MO",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            if match.lastindex:
                return match.group(1).strip()[:160]
            return match.group(0).strip()[:160]
    return "Unknown"


def extract_salary(text: str) -> str:
    match = re.search(r"\$[0-9,]+\s*[-–]\s*\$[0-9,]+", text)
    return match.group(0) if match else "unknown"


def build_markdown(url: str, title: str, company: str, location: str, salary: str, text: str) -> str:
    return (
        f"Source: fetched-url\n"
        f"Apply Link: {url}\n"
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Salary: {salary}\n\n"
        f"## Description\n{text}\n"
    )


def looks_like_listing_page(title: str, text: str) -> bool:
    combined = f"{title}\n{text[:4000]}".lower()
    hard_signals = [
        "jobs at ",
        "careers at ",
        "join our pack",
        "search jobs",
        "all departments",
        "open positions",
        "view all jobs",
        "browse jobs",
    ]
    if any(signal in combined for signal in hard_signals):
        return True
    if title.strip().lower() in {"careers", "jobs", "open positions", "unknown title"}:
        return True
    return False


def main() -> None:
    config = load_json(CONFIG / "sources.json")
    seed_config_path = CONFIG / "company_seeds.json"
    if seed_config_path.exists():
        seed_config = load_json(seed_config_path)
        direct_urls = [item.get("careersUrl", "").strip() for item in seed_config.get("companies", []) if item.get("careersUrl")]
        for source in config.get("sources", []):
            if source.get("name") == "company-careers-direct":
                existing = set(source.get("urls", []))
                for url in direct_urls:
                    if url not in existing:
                        source.setdefault("urls", []).append(url)
                        existing.add(url)
    seen = read_seen_urls()
    INCOMING.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    fetched_log = STATE / "fetched_urls.ndjson"

    for source in config.get("sources", []):
        if not source.get("enabled") or source.get("type") != "direct-url-postings":
            continue
        for url in source.get("urls", []):
            if url in seen:
                print(f"Skip seen URL: {url}")
                continue
            try:
                html = fetch_url(url)
                text = strip_html(html)
                title = extract_title(html, text)
                company = extract_company(url, text)
                location = extract_location(text)
                salary = extract_salary(text)
                if looks_like_listing_page(title, text):
                    append_jsonl(fetched_log, {
                        "fetchedAt": now_iso(),
                        "source": source.get("name", "unknown"),
                        "url": url,
                        "skipped": "listing-page",
                        "title": title,
                    })
                    print(f"Skipped listing page: {url}")
                    continue
                filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{slugify(company)}-{slugify(title)}.md"
                path = INCOMING / filename
                path.write_text(build_markdown(url, title, company, location, salary, text), encoding="utf-8")
                append_jsonl(fetched_log, {
                    "fetchedAt": now_iso(),
                    "source": source.get("name", "unknown"),
                    "url": url,
                    "incomingFile": path.name,
                })
                print(f"Fetched {url} -> {path.name}")
            except Exception as exc:  # noqa: BLE001
                append_jsonl(fetched_log, {
                    "fetchedAt": now_iso(),
                    "source": source.get("name", "unknown"),
                    "url": url,
                    "error": str(exc),
                })
                print(f"Failed {url}: {exc}")


if __name__ == "__main__":
    main()

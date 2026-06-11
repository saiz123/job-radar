#!/usr/bin/env python3
"""Stronger job scraping helper for direct posting URLs.

This script is still lightweight enough to run on a simple server, but it uses
multiple extraction strategies instead of one fragile parser.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "incoming"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"


def now_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "job"


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="ignore")


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


def try_json_ld(html: str) -> dict[str, Any]:
    for match in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>([\s\S]*?)</script>', html, flags=re.IGNORECASE):
        blob = match.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") in {"JobPosting", "Posting"}:
                return item
    return {}


def try_workday_json(html: str) -> dict[str, Any]:
    patterns = [
        r'"jobPostingInfo"\s*:\s*(\{[\s\S]*?\})\s*,\s*"similarJobs"',
        r'"structuredData"\s*:\s*(\{[\s\S]*?\})\s*,\s*"applicantCountry"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if not match:
            continue
        blob = match.group(1)
        try:
            return json.loads(blob)
        except Exception:
            continue
    return {}


def extract_title(html: str, text: str, data: dict[str, Any]) -> str:
    for key in ["title", "name"]:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:200]
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if match:
        title = unescape(re.sub(r"<[^>]+>", " ", match.group(1))).strip()
        return title.split("|")[0].strip()[:200]
    first_line = text.splitlines()[0].strip() if text.splitlines() else "Unknown Title"
    return first_line[:200]


def extract_company(url: str, text: str, data: dict[str, Any]) -> str:
    hiring = data.get("hiringOrganization")
    if isinstance(hiring, dict):
        name = hiring.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()[:160]
    if "wd1.myworkdayjobs.com" in url:
        return url.split("//", 1)[-1].split(".", 1)[0].title()
    for line in text.splitlines()[:12]:
        line = line.strip()
        if line and len(line.split()) <= 6 and "job" not in line.lower():
            return line[:160]
    return "Unknown"


def extract_location(text: str, data: dict[str, Any]) -> str:
    jl = data.get("jobLocation")
    if isinstance(jl, dict):
        addr = jl.get("address", {}) if isinstance(jl.get("address"), dict) else {}
        locality = addr.get("addressLocality", "")
        region = addr.get("addressRegion", "")
        country = addr.get("addressCountry", "")
        loc = ", ".join([part for part in [locality, region, country] if part])
        if loc:
            return loc[:160]
    patterns = [
        r"Location\s*:?\s*(.+)",
        r"Remote\s*-\s*United States",
        r"Hazelwood, MO",
        r"St\. Louis, MO",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return (match.group(1) if match.lastindex else match.group(0)).strip()[:160]
    return "Unknown"


def extract_salary(text: str, data: dict[str, Any]) -> str:
    base = data.get("baseSalary")
    if isinstance(base, dict):
        value = base.get("value")
        if isinstance(value, dict):
            minv = value.get("minValue")
            maxv = value.get("maxValue")
            currency = value.get("currency", "USD")
            if minv or maxv:
                return f"{minv or '?'}-{maxv or '?'} {currency}"
    match = re.search(r"\$[0-9,]+\s*[-–]\s*\$[0-9,]+", text)
    return match.group(0) if match else "unknown"


def build_description(text: str, data: dict[str, Any]) -> str:
    desc = data.get("description")
    if isinstance(desc, str) and desc.strip():
        clean = re.sub(r"<[^>]+>", " ", desc)
        clean = unescape(clean)
        clean = re.sub(r"\s{2,}", " ", clean)
        return clean.strip()
    return text[:12000]


def save_markdown(url: str, title: str, company: str, location: str, salary: str, description: str) -> Path:
    INCOMING.mkdir(parents=True, exist_ok=True)
    filename = f"{now_date()}-{slugify(company)}-{slugify(title)}.md"
    path = INCOMING / filename
    body = (
        f"Source: scraped-url\n"
        f"Apply Link: {url}\n"
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Salary: {salary}\n\n"
        f"## Description\n{description}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()

    html = fetch_html(args.url)
    text = strip_html(html)
    data = try_json_ld(html)
    if not data:
        data = try_workday_json(html)

    title = extract_title(html, text, data)
    company = extract_company(args.url, text, data)
    location = extract_location(text, data)
    salary = extract_salary(text, data)
    description = build_description(text, data)
    path = save_markdown(args.url, title, company, location, salary, description)

    print(json.dumps({
        "incomingFile": str(path),
        "title": title,
        "company": company,
        "location": location,
        "salary": salary,
    }, indent=2))


if __name__ == "__main__":
    main()

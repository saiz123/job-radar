#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from discover_jobs import build_queries, ddg_html_search, extract_links

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
STATE = ROOT / "state"


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


def is_targetish(url: str) -> bool:
    lowered = url.lower()
    return any(token in lowered for token in [
        "greenhouse",
        "lever.co",
        "myworkdayjobs",
        "/jobs/",
        "/job/",
        "cyber",
        "security",
        "soc",
        "incident",
        "threat",
        "iam",
    ])


def main() -> None:
    profile = load_json(CONFIG / "profile.json")
    discovery_cfg = load_json(CONFIG / "discovery.json")
    max_queries = int(discovery_cfg.get("maxQueriesPerRun", 20))
    sleep_ms = int(discovery_cfg.get("sleepBetweenRequestsMs", 1200))

    discovered_path = STATE / "discovered_urls.ndjson"
    run_log = STATE / "discovery_live.ndjson"
    seen = read_seen_urls(discovered_path)

    base_queries = build_queries(profile)
    extra_queries = [
        'site:boards.greenhouse.io ("threat detection" OR "incident response") internship',
        'site:boards.greenhouse.io ("iam security analyst" OR "security assurance analyst")',
        'site:jobs.lever.co ("soc analyst" OR "security operations analyst")',
        'site:myworkdayjobs.com ("cybersecurity analyst" OR "soc analyst")',
        'entry level cybersecurity analyst sponsorship remote united states',
        'security operations analyst opt sponsorship united states',
        'cybersecurity analyst intern remote united states greenhouse',
    ]
    queries = (base_queries + extra_queries)[:max_queries]

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
            links = [u for u in extract_links(html) if is_targetish(u)]
            run["urlsFound"] += len(links)
            for url in links:
                if url in seen:
                    continue
                seen.add(url)
                run["newUrls"] += 1
                append_jsonl(discovered_path, {
                    "discoveredAt": now_iso(),
                    "source": "live-search",
                    "query": query,
                    "url": url,
                })
            time.sleep(sleep_ms / 1000.0)
        except Exception as exc:  # noqa: BLE001
            run["errors"].append({"query": query, "error": str(exc)})
            time.sleep(1.0)

    append_jsonl(run_log, run)
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()

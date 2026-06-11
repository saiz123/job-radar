#!/usr/bin/env python3
"""Autonomous crawler cycle orchestrator.

Runs discovery, attempts scraping of newly discovered URLs, executes ingestion,
then scoring, promotion, and records a machine-readable hourly summary.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
SCRIPTS = ROOT / "scripts"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_py(script_name: str, *args: str, python_bin: Path | None = None) -> tuple[int, str]:
    script = SCRIPTS / script_name
    interpreter = str(python_bin or sys.executable)
    proc = subprocess.run(
        [interpreter, str(script), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, output.strip()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def tail_new_discovered(before_count: int) -> list[dict]:
    items = read_jsonl(STATE / "discovered_urls.ndjson")
    return items[before_count:]


def load_queue_items() -> list[dict]:
    return read_jsonl(STATE / "crawl_queue.ndjson")


def enqueue_new_urls(items: list[dict]) -> int:
    queue_path = STATE / "crawl_queue.ndjson"
    existing = load_queue_items()
    seen = {item.get("url") for item in existing if item.get("url")}
    added = 0
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        append_jsonl(queue_path, {
            "queuedAt": now_iso(),
            "url": url,
            "status": "pending",
            "source": item.get("source", "discovery"),
        })
        added += 1
    return added


def rewrite_queue(items: list[dict]) -> None:
    queue_path = STATE / "crawl_queue.ndjson"
    lines = ['{"_comment":"Append candidate URLs here for queued scraping with status tracking."}']
    for item in items:
        lines.append(json.dumps(item, ensure_ascii=False))
    queue_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_job_url(url: str) -> str:
    raw = unescape(url.strip())
    parts = urlsplit(raw)
    keep_params = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in {"rut", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "source"}:
            continue
        keep_params.append((key, value))
    clean_query = urlencode(keep_params, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, ""))


def count_today_processed_files() -> int:
    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return len(list((ROOT / "processed").glob(f"{today_prefix}-*.json")))


def main() -> None:
    crawler_state_path = STATE / "crawler_state.json"
    crawler_state = load_json(crawler_state_path)

    discovered_before = len(read_jsonl(STATE / "discovered_urls.ndjson"))
    jobs_before = len(read_jsonl(STATE / "jobs.ndjson"))
    shortlist_before = len(read_jsonl(STATE / "shortlist.ndjson"))
    promoted_before = len(read_jsonl(STATE / "promoted_shortlist.ndjson"))
    processed_before = count_today_processed_files()

    summary = {
        "runAt": now_iso(),
        "discovery": {},
        "scrape": {"attempted": 0, "succeeded": 0, "failed": 0},
        "jobspyIngest": {},
        "pipeline": {},
        "promotion": {},
        "alerts": {},
        "notes": [],
    }

    discovery_runs = []
    for script_name in ["discover_jobs.py", "crawl_greenhouse.py", "crawl_lever.py"]:
        code, output = run_py(script_name)
        discovery_runs.append({"script": script_name, "code": code, "output": output})
    summary["discovery"] = discovery_runs

    new_urls = tail_new_discovered(discovered_before)
    summary["queueAdded"] = enqueue_new_urls(new_urls)

    queue_items = load_queue_items()
    scrape_limit = 10
    processed = 0
    for item in queue_items:
        if processed >= scrape_limit:
            break
        if item.get("status") not in {"pending", "retry"}:
            continue
        url = item.get("url", "")
        if not url:
            continue
        clean_url = normalize_job_url(url)
        summary["scrape"]["attempted"] += 1
        code, out = run_py("scrape_job.py", clean_url)
        item["lastTriedAt"] = now_iso()
        item["normalizedUrl"] = clean_url
        if code == 0:
            summary["scrape"]["succeeded"] += 1
            item["status"] = "scraped"
        else:
            summary["scrape"]["failed"] += 1
            item["status"] = "retry"
            item["lastError"] = out[:500]
            summary["notes"].append(f"scrape failed: {clean_url}")
        processed += 1
    rewrite_queue(queue_items)

    if VENV_PYTHON.exists():
        code, output = run_py("jobspy_ingest.py", python_bin=VENV_PYTHON)
        summary["jobspyIngest"] = {"code": code, "output": output}
    else:
        summary["jobspyIngest"] = {"code": 1, "output": "job-hunter/.venv/bin/python not found"}
        summary["notes"].append("jobspy ingest skipped: missing venv interpreter")

    code, output = run_py("run_pipeline.py")
    jobs_after = len(read_jsonl(STATE / "jobs.ndjson"))
    shortlist_after = len(read_jsonl(STATE / "shortlist.ndjson"))
    processed_after = count_today_processed_files()
    summary["pipeline"] = {
        "code": code,
        "output": output,
        "newJobsReviewed": max(0, jobs_after - jobs_before),
        "newShortlist": max(0, shortlist_after - shortlist_before),
        "processedFilesToday": processed_after,
        "newProcessedFilesToday": max(0, processed_after - processed_before),
    }

    code, output = run_py("promote_watch_jobs.py")
    promoted_after = len(read_jsonl(STATE / "promoted_shortlist.ndjson"))
    summary["promotion"] = {
        "code": code,
        "output": output,
        "newPromoted": max(0, promoted_after - promoted_before),
    }

    code, output = run_py("build_promoted_alerts.py")
    summary["alerts"] = {
        "code": code,
        "output": output,
    }

    crawler_state["lastRunAt"] = summary["runAt"]
    crawler_state["lastSummary"] = {
        "newJobsReviewed": summary["pipeline"]["newJobsReviewed"],
        "newShortlist": summary["pipeline"]["newShortlist"],
        "newPromoted": summary["promotion"]["newPromoted"],
        "scrapeSucceeded": summary["scrape"]["succeeded"],
        "alerts": summary["alerts"],
    }
    crawler_state["seenUrls"] = len(read_jsonl(STATE / "discovered_urls.ndjson"))
    crawler_state["runs"] = int(crawler_state.get("runs", 0)) + 1
    save_json(crawler_state_path, crawler_state)

    append_jsonl(STATE / "hourly_summary.ndjson", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

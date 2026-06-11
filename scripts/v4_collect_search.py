#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
CONFIG = ROOT / "config"
OUTPUT = STATE / "v4_search_results.json"
RUN_LOG = STATE / "v4_collect_search.log"
RAW_DIR = STATE / "v4-raw-search"
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"

JOB_HOST_HINTS = {
    "greenhouse.io",
    "job-boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "smartrecruiters.com",
    "jobs.smartrecruiters.com",
    "myworkdayjobs.com",
    "wd1.myworkdayjobs.com",
    "wd5.myworkdayjobs.com",
    "workdayjobs.com",
    "icims.com",
    "careers.icims.com",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "jobvite.com",
    "workable.com",
    "dayforcehcm.com",
    "eightfold.ai",
}

ALLOWED_AGGREGATOR_HOSTS = {
    "builtin.com",
    "www.builtin.com",
    "remoterocketship.com",
    "www.remoterocketship.com",
    "pitchmeai.com",
    "www.useparallel.com",
}

DENY_HOST_PATTERNS = (
    "indeed.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "linkedin.com",
    "cybernoweducation.com",
    "eccouncil.org",
    "offsec.com",
    "paloaltonetworks.com",
    "comptia.org",
    "devo.com",
    "cybersecurityjobsite.com",
    "coursera.org",
    "udemy.com",
    "youtube.com",
)

GENERIC_QUERIES = [
    {
        "company": "",
        "title": "Entry-Level SOC Analyst",
        "query": '"Entry-Level SOC Analyst" (remote OR "United States") cybersecurity job',
    },
    {
        "company": "",
        "title": "Cybersecurity Analyst",
        "query": '"Cybersecurity Analyst" (remote OR "United States") incident response job',
    },
    {
        "company": "",
        "title": "Security Operations Analyst",
        "query": '"Security Operations Analyst" (remote OR "United States") cybersecurity job',
    },
    {
        "company": "",
        "title": "Security Analyst",
        "query": '"Security Analyst" (remote OR "United States") siem job',
    },
]


@dataclass
class QuerySpec:
    company: str
    title: str
    query: str
    source_domain: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_openclaw_config() -> dict[str, Any]:
    return json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))


def gateway_endpoint() -> tuple[str, str]:
    cfg = load_openclaw_config()
    port = int(cfg["gateway"]["port"])
    token = str(cfg["gateway"]["auth"]["token"])
    return f"http://127.0.0.1:{port}/tools/invoke", token


def invoke_tool(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    url, token = gateway_endpoint()
    body = json.dumps({"tool": tool, "args": args}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"tool {tool} failed with HTTP {exc.code}: {detail}") from exc
    details = payload.get("result", {}).get("details")
    if isinstance(details, dict):
        return details
    content = payload.get("result", {}).get("content") or []
    if content and isinstance(content[0], dict):
        text = content[0].get("text") or "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"rawText": text}
    return payload


def strip_wrapped(text: str) -> str:
    clean = re.sub(r"<<<EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>", "", text or "")
    clean = re.sub(r"<<<END_EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>", "", clean)
    clean = clean.replace("Source: Web Search", "").strip()
    return re.sub(r"\n{3,}", "\n\n", clean)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def build_queries(max_queries: int) -> list[QuerySpec]:
    companies = json.loads((CONFIG / "company_seeds.json").read_text(encoding="utf-8")).get("companies", [])
    titles = [
        "SOC Analyst",
        "Cybersecurity Analyst",
        "Security Operations Analyst",
    ]
    specs: list[QuerySpec] = []
    for company in sorted(companies, key=lambda item: (int(item.get("priority", 9)), item.get("company", ""))):
        domain = host_of(company.get("careersUrl", ""))
        company_name = company.get("company", "").strip()
        for title in titles[: 2 if int(company.get("priority", 9)) <= 1 else 1]:
            query = f'site:{domain} "{title}" "{company_name}" (remote OR "United States" OR Missouri OR Virginia OR Texas) job'
            specs.append(QuerySpec(company=company_name, title=title, query=query, source_domain=domain))
    for item in GENERIC_QUERIES:
        specs.append(QuerySpec(company=item["company"], title=item["title"], query=item["query"], source_domain=""))
    return specs[:max_queries]


def citation_score(spec: QuerySpec, citation: dict[str, Any], summary: str) -> int:
    url = str(citation.get("url") or "")
    title = normalize_space(str(citation.get("title") or "")).lower()
    host = host_of(url)
    path = urllib.parse.urlparse(url).path.lower()
    score = 0
    if not url or host.startswith("www.google."):
        return -999
    if any(pattern in host for pattern in DENY_HOST_PATTERNS):
        return -120
    if host == spec.source_domain and spec.source_domain:
        score += 50
    if spec.company and spec.company.lower().replace(" ", "") in host.replace("-", "").replace(".", ""):
        score += 25
    if any(hint in host for hint in JOB_HOST_HINTS):
        score += 22
    if host in ALLOWED_AGGREGATOR_HOSTS:
        score += 10
    if any(token in path for token in ("/jobs/", "/job/", "/positions/", "/openings/", "/career/")):
        score += 18
    if any(token in url.lower() for token in ("greenhouse", "workday", "smartrecruiters", "lever", "icims", "ashby")):
        score += 10
    if spec.company and spec.company.lower() in title:
        score += 8
    if spec.title.lower() in title:
        score += 6
    if "search" in path and "/jobs/" not in path:
        score -= 25
    if any(token in path for token in ("/resources/", "/blog/", "/topics/", "/guide/", "/learn/")):
        score -= 35
    if path.rstrip("/") in ("", "/careers", "/careers/"):
        score -= 30
    if "page=" in url.lower():
        score -= 20
    summary_l = summary.lower()
    if spec.company and spec.company.lower() in summary_l:
        score += 6
    if spec.title.lower() in summary_l:
        score += 6
    return score


def infer_location(summary: str) -> str:
    text = normalize_space(summary)
    lower = text.lower()
    if "remote" in lower:
        if "united states" in lower:
            return "Remote, United States"
        return "Remote"
    patterns = [
        r"located in ([A-Z][A-Za-z .,-]+?)(?:[.\n]|, which|, and|, with|$)",
        r"in ([A-Z][A-Za-z .,-]+, [A-Z][A-Za-z .]+)(?:[.\n]|, and|, with|$)",
        r"based in ([A-Z][A-Za-z .,-]+?)(?:[.\n]|, and|, with|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(" ,")
    states = ["Missouri", "Virginia", "Texas", "North Carolina", "Georgia", "Illinois", "Florida"]
    for state in states:
        if state.lower() in lower:
            return state
    return "Unknown"


def normalize_title(spec: QuerySpec, summary: str) -> str:
    if spec.title:
        return spec.title
    first = normalize_space(summary).split(".", 1)[0]
    return first[:120] if first else "Unknown title"


def should_keep(spec: QuerySpec, summary: str, best_url: str) -> tuple[bool, str]:
    text = normalize_space(summary).lower()
    host = host_of(best_url)
    path = urllib.parse.urlparse(best_url).path.lower()
    if not best_url:
        return False, "no_usable_citation"
    if len(text) < 60:
        return False, "thin_summary"
    if any(phrase in text for phrase in [
        "unable to find any direct job postings",
        "couldn't find any direct job postings",
        "could not find any direct",
        "no direct job postings",
        "did not yield specific job postings",
        "was not explicitly found",
        "none of the provided snippets led directly to a job listing",
        "career pages indicate",
    ]):
        return False, "no_specific_posting_found"
    if not any(word in text for word in ["analyst", "soc", "incident", "security", "cyber"]):
        return False, "not_security_job_like"
    if spec.company and spec.company.lower() not in text[:280] and spec.company.lower() not in host:
        return False, "company_not_grounded"
    if any(phrase in text for phrase in [
        "typically involves",
        "what is a soc analyst",
        "career guide",
        "how to become",
        "job market",
    ]):
        return False, "generic_explainer"
    if any(phrase in text for phrase in ["director", "principal", "staff", "senior security engineer"]):
        return False, "senior_only"
    if host not in ALLOWED_AGGREGATOR_HOSTS and not any(hint in host for hint in JOB_HOST_HINTS):
        if not any(token in path for token in ("/jobs/", "/job/", "/positions/", "/openings/")):
            return False, "url_not_job_like"
    if path.rstrip("/") in ("", "/careers", "/careers/", "/careers/jobs"):
        return False, "career_homepage"
    if "search" in path and "/jobs/" not in path:
        return False, "search_results_page"
    if "page=" in best_url.lower():
        return False, "paginated_listing_page"
    if any(phrase in text for phrase in ["clearance", "ts/sci", "polygraph", "public trust"]):
        return True, "authorization_risk_but_reviewable"
    return True, "ok"


def collect(max_queries: int, count: int) -> dict[str, Any]:
    run_at = now_iso()
    specs = build_queries(max_queries=max_queries)
    items: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    blocked = 0

    for spec in specs:
        try:
            details = invoke_tool("web_search", {"query": spec.query, "count": count})
        except Exception as exc:
            blocked += 1
            raw_results.append({
                "query": spec.query,
                "company": spec.company,
                "title": spec.title,
                "decision": "tool_error",
                "error": str(exc),
            })
            continue
        summary = strip_wrapped(str(details.get("content") or ""))
        citations = details.get("citations") or []
        ranked = sorted(citations, key=lambda c: citation_score(spec, c, summary), reverse=True)
        best = ranked[0] if ranked and citation_score(spec, ranked[0], summary) > 0 else None
        best_url = str(best.get("url") or "") if best else ""
        keep, reason = should_keep(spec, summary, best_url)
        raw_results.append({
            "query": spec.query,
            "company": spec.company,
            "title": spec.title,
            "citations": citations,
            "selectedUrl": best_url,
            "decision": reason,
            "summary": summary,
        })
        if not keep or not best_url or best_url in seen_urls:
            blocked += 1
            continue
        seen_urls.add(best_url)
        items.append({
            "query": spec.query,
            "title": normalize_title(spec, summary),
            "company": spec.company or (host_of(best_url).split(":")[0] if best_url else "Unknown"),
            "location": infer_location(summary),
            "url": best_url,
            "snippet": summary[:900],
            "posted_hint": f"fresh via automated web search {run_at}",
            "source_domain": host_of(best_url),
        })

    payload = {
        "generatedAt": run_at,
        "queryCount": len(specs),
        "accepted": len(items),
        "rejected": blocked,
        "items": items,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{run_at.replace(':', '').replace('-', '')}.json").write_text(
        json.dumps({"generatedAt": run_at, "results": raw_results}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "runAt": run_at,
            "queryCount": len(specs),
            "accepted": len(items),
            "rejected": blocked,
            "output": str(OUTPUT),
        }, ensure_ascii=False) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-queries", type=int, default=18)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(collect(max_queries=args.max_queries, count=args.count), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

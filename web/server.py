#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
DB_PATH = STATE / "staffing_v4.sqlite3"
HOST = "127.0.0.1"
PORT = 8765


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


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def compact_job(item: dict) -> dict:
    return {
        "reviewedAt": item.get("reviewedAt", ""),
        "jobId": item.get("jobId", ""),
        "title": item.get("title", ""),
        "company": item.get("company", ""),
        "location": item.get("location", ""),
        "score": int(item.get("score", 0)),
        "decision": item.get("decision", ""),
        "link": item.get("link", ""),
        "sponsorshipStatus": item.get("sponsorshipStatus", "unknown"),
        "authorizationRisk": item.get("authorizationRisk", "medium"),
        "reasons": item.get("reasons", [])[:4],
        "matchedSkills": item.get("matchedSkills", [])[:5],
        "missingSkills": item.get("missingSkills", [])[:5],
        "notes": item.get("notes", ""),
    }


def v3_summary() -> dict:
    if not DB_PATH.exists():
        return {"leads": 0, "canonicalJobs": 0, "applicationsTracked": 0, "verified": 0, "appliable": 0, "alertsQueued": 0}
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        out = {}
        cur.execute("SELECT COUNT(*) FROM jobs")
        out["leads"] = cur.fetchone()[0]
        out["canonicalJobs"] = out["leads"]
        cur.execute("SELECT COUNT(*) FROM resume_versions")
        out["applicationsTracked"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('appliable', 'shortlisted')")
        out["verified"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM jobs WHERE overall_score >= 70")
        out["appliable"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM jobs WHERE overall_score >= 85")
        out["alertsQueued"] = cur.fetchone()[0]
        return out
    finally:
        conn.close()


def dashboard_payload() -> dict:
    db_jobs = []
    resume_versions = []
    queued_alerts = []
    sent_alerts = 0
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, company, title, location, url as official_url, source as ats_type,
                       sponsorship_score as sponsorship_status, notes as authorization_risk,
                       overall_score as cyber_score, experience_score as entry_level_score,
                       ats_score as placement_score, status, summary, updated_at
                FROM jobs
                ORDER BY overall_score DESC, ats_score DESC, experience_score DESC, id DESC
                LIMIT 40
                """
            )
            db_jobs = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT rv.job_id, rv.version_label, rv.resume_path, rv.fit_notes_path, rv.ats_score,
                       rv.created_at, j.company, j.title, j.url
                FROM resume_versions rv
                JOIN jobs j ON j.id = rv.job_id
                ORDER BY rv.created_at DESC
                LIMIT 20
                """
            )
            resume_versions = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT n.job_id, n.score, n.confidence_tier, n.status, j.company, j.title, j.url
                FROM staffing_notifications n
                JOIN jobs j ON j.id = n.job_id
                WHERE n.status = 'queued'
                ORDER BY n.score DESC, n.job_id DESC
                LIMIT 20
                """
            )
            queued_alerts = [
                {
                    "jobId": f"v4-{row['job_id']}",
                    "score": row["score"],
                    "confidenceTier": row["confidence_tier"],
                    "company": row["company"],
                    "title": row["title"],
                    "link": row["url"],
                }
                for row in cur.fetchall()
            ]
            cur.execute("SELECT COUNT(*) FROM staffing_notifications WHERE status = 'sent'")
            sent_alerts = int(cur.fetchone()[0])
        finally:
            conn.close()

    active_jobs = [
        {
            "reviewedAt": job.get("updated_at", ""),
            "jobId": job.get("id", ""),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "score": int(job.get("cyber_score", 0)),
            "decision": job.get("status", ""),
            "link": job.get("official_url", ""),
            "sponsorshipStatus": str(job.get("sponsorship_status", "unknown")),
            "authorizationRisk": job.get("authorization_risk", "medium"),
            "reasons": [job.get("summary", "web-search match")],
            "matchedSkills": [],
            "missingSkills": [],
            "notes": job.get("authorization_risk", ""),
        }
        for job in db_jobs
    ]

    decisions = {}
    for item in active_jobs:
        decision = item.get("decision", "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1

    return {
        "summary": {
            "reviewed": len(db_jobs),
            "promoted": len([j for j in db_jobs if int(j.get("cyber_score") or 0) >= 85]),
            "queuedAlerts": len(queued_alerts),
            "sentAlerts": sent_alerts,
            "applications": len(resume_versions),
            "discovered": len(db_jobs),
            "active": len(active_jobs),
            "decisions": decisions,
            "v3": v3_summary(),
            "dailyGoal": {
                "date": "2026-04-17",
                "dailyAppliableTarget": 15,
                "appliableFound": len([j for j in db_jobs if int(j.get("cyber_score") or 0) >= 70]),
                "targetReached": len([j for j in db_jobs if int(j.get("cyber_score") or 0) >= 70]) >= 15,
            },
        },
        "activeJobs": active_jobs,
        "topJobs": active_jobs,
        "latestDiscovered": [
            {
                "discoveredAt": job.get("updated_at", ""),
                "source": job.get("ats_type", "web_search"),
                "company": job.get("company", ""),
                "title": job.get("title", ""),
                "location": job.get("location", ""),
                "url": job.get("official_url", ""),
            }
            for job in db_jobs
        ],
        "applications": [
            {
                "company": item.get("company", ""),
                "title": item.get("title", ""),
                "status": item.get("version_label", "v1"),
                "score": item.get("ats_score", 0),
                "link": item.get("url", ""),
                "resume_path": item.get("resume_path", ""),
            }
            for item in resume_versions
        ],
        "promoted": queued_alerts,
        "queuedAlerts": queued_alerts,
        "staffingJobs": db_jobs,
    }


HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Staffing Desk</title>
  <style>
    :root {
      --bg: #08111f;
      --panel: #101a2c;
      --panel-2: #16233a;
      --muted: #8ea2c5;
      --text: #e9eef8;
      --line: #223252;
      --accent: #6ea8fe;
      --good: #4fd1a5;
      --warn: #f6ad55;
      --bad: #fc8181;
      --shadow: 0 12px 28px rgba(0,0,0,.28);
      --radius: 16px;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: linear-gradient(180deg, #08111f 0%, #0c1526 100%); color: var(--text); }
    .shell { display: grid; grid-template-columns: 240px minmax(0, 1fr) 320px; min-height: 100vh; }
    .sidebar { border-right: 1px solid var(--line); background: rgba(8,17,31,.88); padding: 24px 18px; position: sticky; top: 0; height: 100vh; }
    .brand { font-size: 22px; font-weight: 800; margin-bottom: 8px; }
    .sub { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
    .nav-group { margin-bottom: 24px; }
    .nav-title { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 10px; }
    .nav-item { display: block; padding: 10px 12px; border-radius: 12px; color: var(--text); text-decoration: none; margin-bottom: 6px; background: transparent; }
    .nav-item.active, .nav-item:hover { background: var(--panel-2); }
    .main { padding: 28px; min-width: 0; }
    .topbar { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 24px; }
    .headline { font-size: 28px; font-weight: 800; margin: 0; }
    .muted { color: var(--muted); }
    .search { width: 320px; max-width: 100%; background: var(--panel); border: 1px solid var(--line); color: var(--text); border-radius: 14px; padding: 12px 14px; }
    .cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 22px; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; box-shadow: var(--shadow); }
    .card .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .card .value { font-size: 28px; font-weight: 800; margin-top: 6px; }
    .section-card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); margin-bottom: 18px; overflow: hidden; }
    .section-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--line); }
    .section-title { font-size: 18px; font-weight: 700; }
    .job-list { padding: 10px; }
    .job-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; padding: 14px; border-radius: 14px; border: 1px solid transparent; margin-bottom: 10px; background: #0f1829; }
    .job-row:hover { border-color: var(--line); background: #13203a; }
    .job-title { font-size: 17px; font-weight: 700; margin-bottom: 5px; }
    .job-meta { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
    .chips { display: flex; gap: 8px; flex-wrap: wrap; }
    .chip { padding: 6px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); background: #13203a; color: var(--text); }
    .chip.good { color: var(--good); }
    .chip.warn { color: var(--warn); }
    .chip.bad { color: var(--bad); }
    .score { min-width: 86px; text-align: center; background: #13203a; border: 1px solid var(--line); border-radius: 16px; padding: 10px; align-self: start; }
    .score-num { font-size: 28px; font-weight: 800; }
    .score-label { color: var(--muted); font-size: 12px; }
    .panel { border-left: 1px solid var(--line); background: rgba(8,17,31,.88); padding: 24px 18px; }
    .mini-list { display: grid; gap: 10px; }
    .mini-item { padding: 12px; border-radius: 12px; background: var(--panel); border: 1px solid var(--line); }
    .mini-title { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
    .mini-meta { font-size: 12px; color: var(--muted); }
    a { color: var(--accent); text-decoration: none; }
    @media (max-width: 1200px) { .shell { grid-template-columns: 220px minmax(0, 1fr); } .panel { display: none; } }
    @media (max-width: 860px) { .shell { grid-template-columns: 1fr; } .sidebar { display: none; } .main { padding: 18px; } .cards { grid-template-columns: 1fr 1fr; } .topbar { flex-direction: column; align-items: stretch; } .search { width: 100%; } }
  </style>
</head>
<body>
  <div class=\"shell\">
    <aside class=\"sidebar\">
      <div class=\"brand\">Staffing Desk</div>
      <div class=\"sub\">Jody-run job automation</div>
      <div class=\"nav-group\">
        <div class=\"nav-title\">Views</div>
        <a class=\"nav-item active\" href=\"#\">Dashboard</a>
        <a class=\"nav-item\" href=\"#staffing-jobs\">Staffing jobs</a>
        <a class=\"nav-item\" href=\"#active-jobs\">Legacy scored jobs</a>
        <a class=\"nav-item\" href=\"#discovery\">Discovery</a>
        <a class=\"nav-item\" href=\"#applications\">Applications</a>
      </div>
    </aside>
    <main class=\"main\">
      <div class=\"topbar\">
        <div>
          <h1 class=\"headline\">Staffing Automation</h1>
          <div class=\"muted\">Database-backed jobs, score tracking, and alert queue.</div>
        </div>
        <input id=\"search\" class=\"search\" placeholder=\"Search company, role, source...\" />
      </div>
      <div id=\"app\">Loading...</div>
    </main>
    <aside class=\"panel\">
      <div class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Promoted leads</div></div><div id=\"promoted\" class=\"mini-list\" style=\"padding:12px\"></div></div>
      <div class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Applications</div></div><div id=\"applications-side\" class=\"mini-list\" style=\"padding:12px\"></div></div>
      <div class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Queued alerts</div></div><div id=\"alerts-side\" class=\"mini-list\" style=\"padding:12px\"></div></div>
    </aside>
  </div>
  <script>
    let DATA = null;
    function esc(v) { return String(v ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c] || c)); }
    function chip(text, klass='') { return `<span class=\"chip ${klass}\">${esc(text)}</span>`; }
    function sponsorshipChip(status) {
      if (status === 'yes' || status === 'likely') return chip(status, 'good');
      if (status === 'blocked' || status === 'unlikely' || status === 'likely-no') return chip(status, 'bad');
      return chip(status || 'unknown', 'warn');
    }
    function jobCard(j) {
      const reasons = (j.reasons || []).slice(0, 3).map(r => chip(r)).join('');
      const skills = (j.matchedSkills || []).slice(0, 3).map(s => chip(s)).join('');
      return `<div class=\"job-row\"><div><div class=\"job-title\">${esc(j.title)}</div><div class=\"job-meta\">${esc(j.company)} · ${esc(j.location)} · ${esc(j.decision)}${j.link ? ` · <a href=\"${esc(j.link)}\" target=\"_blank\">open</a>` : ''}</div><div class=\"chips\">${sponsorshipChip(j.sponsorshipStatus)}${reasons}${skills}</div></div><div class=\"score\"><div class=\"score-num\">${esc(j.score)}</div><div class=\"score-label\">match</div></div></div>`;
    }
    function mini(items, mapper) { return items.length ? items.map(mapper).join('') : `<div class=\"mini-item\"><div class=\"mini-meta\">Nothing here yet.</div></div>`; }
    function render(filter='') {
      const data = DATA;
      const s = data.summary;
      const q = filter.trim().toLowerCase();
      const filteredActive = data.activeJobs.filter(j => (`${j.company} ${j.title} ${j.location} ${j.decision} ${j.sponsorshipStatus}`).toLowerCase().includes(q) || !q);
      const filteredDiscovered = data.latestDiscovered.filter(j => (`${j.company || ''} ${j.title || ''} ${j.source || ''} ${j.url || ''}`).toLowerCase().includes(q) || !q);
      const filteredStaffing = (data.staffingJobs || []).filter(j => (`${j.company || ''} ${j.title || ''} ${j.location || ''} ${j.sponsorship_status || ''}`).toLowerCase().includes(q) || !q);

      const cards = `<div class=\"cards\">
        <div class=\"card\"><div class=\"label\">Reviewed</div><div class=\"value\">${s.reviewed}</div></div>
        <div class=\"card\"><div class=\"label\">Active leads</div><div class=\"value\">${s.active}</div></div>
        <div class=\"card\"><div class=\"label\">Queued alerts</div><div class=\"value\">${s.queuedAlerts}</div></div>
        <div class=\"card\"><div class=\"label\">Sent alerts</div><div class=\"value\">${s.sentAlerts}</div></div>
        <div class=\"card\"><div class=\"label\">Appliable today</div><div class=\"value\">${s.v3.appliable}</div></div>
        <div class=\"card\"><div class=\"label\">Daily target</div><div class=\"value\">${(s.dailyGoal.dailyAppliableTarget || 15)}</div></div>
        <div class=\"card\"><div class=\"label\">Goal progress</div><div class=\"value\">${(s.dailyGoal.appliableFound || 0)}</div></div>
        <div class=\"card\"><div class=\"label\">Canonical jobs</div><div class=\"value\">${s.v3.canonicalJobs}</div></div>
        <div class=\"card\"><div class=\"label\">Verified leads</div><div class=\"value\">${s.v3.verified}</div></div>
      </div>`;

      const staffingSection = `<section id=\"staffing-jobs\" class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Staffing automation jobs</div><div class=\"muted\">DB-backed appliable opportunities</div></div><div class=\"job-list\">${filteredStaffing.length ? filteredStaffing.map(j => `<div class=\"job-row\"><div><div class=\"job-title\">${esc(j.title)}</div><div class=\"job-meta\">${esc(j.company)} · ${esc(j.location || 'Unknown')} · ${esc(j.ats_type || 'source')}</div><div class=\"chips\">${sponsorshipChip(j.sponsorship_status)}${chip(`cyber ${j.cyber_score}`)}${chip(`entry ${j.entry_level_score}`)}${chip(`fit ${j.placement_score}`, j.placement_score >= 75 ? 'good' : (j.placement_score >= 65 ? 'warn' : ''))}</div><div class=\"job-meta\" style=\"margin-top:8px\"><a href=\"${esc(j.official_url)}\" target=\"_blank\">apply link</a></div></div><div class=\"score\"><div class=\"score-num\">${esc(j.placement_score)}</div><div class=\"score-label\">fit</div></div></div>`).join('') : `<div class=\"job-row\"><div><div class=\"job-title\">No staffing jobs matched</div><div class=\"job-meta\">Run the staffing loop or broaden sources.</div></div></div>`}</div></section>`;

      const activeSection = `<section id=\"active-jobs\" class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Legacy scored jobs</div><div class=\"muted\">watch / alert / tailor-ready</div></div><div class=\"job-list\">${filteredActive.length ? filteredActive.map(jobCard).join('') : `<div class=\"job-row\"><div><div class=\"job-title\">No active jobs matched</div><div class=\"job-meta\">Try a different search.</div></div></div>`}</div></section>`;

      const discoverySection = `<section id=\"discovery\" class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Latest discovered posting URLs</div><div class=\"muted\">${filteredDiscovered.length} visible</div></div><div style=\"padding:12px\" class=\"mini-list\">${filteredDiscovered.map(j => `<div class=\"mini-item\"><div class=\"mini-title\">${esc(j.title || 'Untitled discovery')}</div><div class=\"mini-meta\">${esc(j.company || 'Unknown')} · ${esc(j.source || 'unknown')}</div><div class=\"mini-meta\"><a href=\"${esc(j.url || '#')}\" target=\"_blank\">Open URL</a></div></div>`).join('') || `<div class=\"mini-item\"><div class=\"mini-meta\">No discovered URLs matched.</div></div>`}</div></section>`;

      const appsSection = `<section id=\"applications\" class=\"section-card\"><div class=\"section-head\"><div class=\"section-title\">Applications</div><div class=\"muted\">tracked packages</div></div><div style=\"padding:12px\" class=\"mini-list\">${mini(data.applications, a => `<div class=\"mini-item\"><div class=\"mini-title\">${esc(a.title)}</div><div class=\"mini-meta\">${esc(a.company)} · ${esc(a.status)} · score ${esc(a.score)}</div><div class=\"mini-meta\">${a.link ? `<a href=\"${esc(a.link)}\" target=\"_blank\">Open job</a>` : ''}</div></div>`)}</div></section>`;

      document.getElementById('app').innerHTML = cards + staffingSection + activeSection + discoverySection + appsSection;
      document.getElementById('promoted').innerHTML = mini(data.promoted, p => `<div class=\"mini-item\"><div class=\"mini-title\">${esc(p.title)}</div><div class=\"mini-meta\">${esc(p.company)} · ${esc(p.confidenceTier || '')} · score ${esc(p.score || '')}</div></div>`);
      document.getElementById('applications-side').innerHTML = mini(data.applications, a => `<div class=\"mini-item\"><div class=\"mini-title\">${esc(a.company)}</div><div class=\"mini-meta\">${esc(a.title)} · ${esc(a.status)}</div></div>`);
      document.getElementById('alerts-side').innerHTML = mini(data.queuedAlerts, a => `<div class=\"mini-item\"><div class=\"mini-title\">${esc(a.jobId || 'alert')}</div><div class=\"mini-meta\">score ${esc(a.score || '')} · ${esc(a.confidenceTier || 'queued')}</div></div>`);
    }
    async function load() { const res = await fetch('/api/dashboard'); DATA = await res.json(); render(''); document.getElementById('search').addEventListener('input', (e) => render(e.target.value)); }
    load();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            payload = dashboard_payload()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Dashboard running at http://{HOST}:{PORT}")
    server.serve_forever()

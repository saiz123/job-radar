from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, Header, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse

from .auth import SessionStore
from .config import Settings, get_settings
from .db import (
    attach_evaluation,
    complete_followup,
    create_company,
    create_contact,
    create_document,
    create_interview,
    create_resume_base,
    compile_resume_variant,
    create_scan,
    delete_company,
    delete_contact,
    delete_document,
    delete_interview,
    get_analytics,
    get_automation_status,
    get_company,
    get_contact,
    get_db_summary,
    get_digest,
    get_document,
    get_evaluation_queue,
    get_followups_due,
    get_health,
    get_interview,
    get_job,
    get_job_resume_workspace,
    get_latest_scan,
    get_pipeline,
    get_readiness,
    get_resume_events,
    get_resume_variant,
    get_resume_variant_ats,
    get_resume_variant_download,
    generate_resume_hm_audit,
    get_scan,
    import_legacy_processed,
    import_manual_job,
    ingest_scan,
    init_db,
    list_resume_bases,
    accept_all_safe_resume_suggestions,
    list_automation_failures,
    list_automation_runs,
    list_applications,
    list_companies,
    list_contacts,
    list_documents,
    list_interviews,
    list_resume_variants_for_job,
    accept_resume_suggestion,
    mark_job_applied,
    list_jobs,
    list_scans,
    move_pipeline_job,
    prepare_job_application,
    analyze_resume_fit,
    refresh_liveness,
    tailor_resume_for_job,
    update_resume_variant_source,
    retry_ingest_failure,
    search_resources,
    update_job_application_status,
    update_company,
    update_contact,
    update_document,
    update_interview,
)


def require_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
    x_jobradar_actor: str | None = Header(default=None),
) -> str:
    if settings.disable_login:
        return f"service:{x_jobradar_actor}" if x_jobradar_actor else "browser:test-mode"
    expected = settings.service_token
    if expected and authorization == f"Bearer {expected}" and x_jobradar_actor:
        return f"service:{x_jobradar_actor}"
    session_id = request.cookies.get(settings.session_cookie)
    store = SessionStore(settings)
    if not session_id or not store.exists(session_id):
        raise PermissionError("unauthorized")
    return session_id


def require_write_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
    x_jobradar_actor: str | None = Header(default=None),
    x_csrf_token: str | None = Header(default=None),
) -> str:
    if settings.disable_login:
        return f"service:{x_jobradar_actor}" if x_jobradar_actor else "browser:test-mode"
    actor = require_session(
        request=request,
        settings=settings,
        authorization=authorization,
        x_jobradar_actor=x_jobradar_actor,
    )
    if actor.startswith("service:"):
        return actor
    if not SessionStore(settings).matches_csrf(actor, x_csrf_token):
        raise ValueError("csrf_required")
    return actor


def require_cloudflare_write_access(
    request: Request,
    settings: Settings = Depends(get_settings),
    cf_access_jwt_assertion: str | None = Header(default=None),
    cf_access_authenticated_user_email: str | None = Header(default=None),
) -> None:
    if settings.disable_login or not settings.require_cloudflare_access:
        return None
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if cf_access_jwt_assertion or cf_access_authenticated_user_email:
        return None
    raise PermissionError("cloudflare_access_required")


LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow,noarchive,nosnippet" />
  <title>Job Radar Login</title>
  <style>
    body {{ background: #0d1117; color: #c9d1d9; font-family: system-ui, sans-serif; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
    .card {{ width:min(420px, 92vw); background:#161b22; border:1px solid #30363d; border-radius:16px; padding:24px; }}
    h1 {{ margin:0 0 8px; }}
    p {{ color:#8b949e; }}
    input {{ width:100%; margin:8px 0 16px; padding:12px; border-radius:10px; border:1px solid #30363d; background:#0d1117; color:#c9d1d9; }}
    button {{ width:100%; padding:12px; background:#238636; color:white; border:0; border-radius:10px; font-weight:700; }}
    .err {{ color:#ff7b72; margin-bottom:12px; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>Job Radar</h1>
    <p>Private cybersecurity job search operations center.</p>
    {error_html}
    <form method="post" action="/auth/login">
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>
"""

APP_HTML = """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <meta name=\"robots\" content=\"noindex,nofollow,noarchive,nosnippet\" />
  <title>Job Radar</title>
  <style>
    :root {
      --bg-base:#0b0f12; --bg-surface:#11171b; --bg-raised:#161d22; --bg-overlay:#1c252b;
      --border-subtle:#1f2a31; --border-default:#2a3841; --border-strong:#3b4c57;
      --text-primary:#e6edf3; --text-secondary:#9fb0bd; --text-tertiary:#6b7d8a; --text-inverse:#0b0f12;
      --accent:#3fb98f; --accent-hover:#4fd0a2; --accent-subtle:#12312a;
      --sev-critical:#f0526a; --sev-high:#f08a4b; --sev-medium:#e3c04a; --sev-low:#4fa3d1; --positive:#3fb98f;
      --font-sans:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;
      --font-mono:"JetBrains Mono",ui-monospace,"SFMono-Regular",monospace;
      --sidebar:210px;
    }
    * { box-sizing:border-box; }
    html, body { margin:0; background:var(--bg-base); color:var(--text-primary); font-family:var(--font-sans); font-size:15px; line-height:1.5; -webkit-font-smoothing:antialiased; }
    body { overflow-x:hidden; }
    a { color:inherit; text-decoration:none; }
    button, input { font:inherit; }
    button { background:none; border:none; color:inherit; cursor:pointer; }
    form { margin:0; }
    button, .btn, .chip, .pill { min-height:30px; }
    img, svg, canvas, table { max-width:100%; }
    :focus-visible { outline:none; box-shadow:0 0 0 2px var(--bg-base),0 0 0 4px var(--accent); border-radius:4px; }
    .mono { font-family:var(--font-mono); font-variant-numeric:tabular-nums; }
    .app-shell { display:grid; grid-template-columns:210px 1fr; min-height:100vh; }
    .sidebar { background:var(--bg-surface); border-right:1px solid var(--border-subtle); padding:16px 0; display:flex; flex-direction:column; position:sticky; top:0; height:100vh; overflow:auto; }
    .brand { display:flex; align-items:center; gap:9px; padding:0 16px 24px; }
    .brand-dot { width:9px; height:9px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px var(--accent); flex:none; }
    .brand b { font-size:14px; letter-spacing:-.01em; }
    .brand span { display:block; font-family:var(--font-mono); font-size:9.5px; color:var(--text-tertiary); letter-spacing:.1em; text-transform:uppercase; }
    .nav-group { display:grid; gap:10px; }
    .nav-label { font-family:var(--font-mono); font-size:9.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--text-tertiary); padding:16px 16px 8px; }
    .nav-btn { display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%; padding:7px 16px; font-size:13.5px; color:var(--text-secondary); border-left:2px solid transparent; text-align:left; }
    .nav-btn:hover { background:var(--bg-raised); color:var(--text-primary); }
    .nav-btn.active { background:var(--bg-raised); color:var(--text-primary); border-left-color:var(--accent); font-weight:500; }
    .nav-btn .cnt { font-family:var(--font-mono); font-size:10.5px; color:var(--text-tertiary); }
    .nav-btn.active .cnt { color:var(--accent); }
    .content { min-width:0; }
    .topbar { display:flex; align-items:center; gap:12px; padding:12px 24px; border-bottom:1px solid var(--border-subtle); background:var(--bg-surface); position:sticky; top:0; z-index:40; }
    .search { flex:1; max-width:420px; display:flex; align-items:center; gap:8px; background:var(--bg-base); border:1px solid var(--border-default); border-radius:6px; padding:6px 10px; color:var(--text-secondary); }
    .search input { flex:1; min-width:0; background:transparent; border:none; outline:none; color:var(--text-primary); }
    .search-kbd { margin-left:auto; font-family:var(--font-mono); font-size:10px; border:1px solid var(--border-default); border-radius:3px; padding:1px 5px; color:var(--text-tertiary); }
    .topbar-right { display:flex; gap:8px; flex-wrap:wrap; align-items:center; justify-content:flex-end; min-width:0; }
    .topbar-right form { display:flex; min-width:0; }
    .pill, .chip, .badge { display:inline-flex; align-items:center; gap:6px; font-family:var(--font-mono); font-size:10.5px; border:1px solid var(--border-default); border-radius:100px; padding:4px 10px; color:var(--text-secondary); }
    .pill .live-dot { width:6px; height:6px; border-radius:50%; background:var(--accent); }
    .btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; font-family:var(--font-mono); font-size:11px; letter-spacing:.05em; text-transform:uppercase; padding:6px 12px; border-radius:4px; border:1px solid var(--border-default); color:var(--text-secondary); background:transparent; line-height:1.35; white-space:normal; text-align:center; max-width:100%; }
    .btn:hover { border-color:var(--border-strong); color:var(--text-primary); }
    .btn.primary { background:var(--accent); border-color:var(--accent); color:var(--text-inverse); font-weight:700; }
    .btn.primary:hover { background:var(--accent-hover); }
    .main { padding:24px; max-width:1500px; }
    .section { display:none; }
    .section.active { display:block; }
    .h1 { font-size:21px; font-weight:600; letter-spacing:-.02em; }
    .sub { color:var(--text-tertiary); font-size:13px; margin-top:2px; }
    .sechead { display:flex; align-items:baseline; gap:12px; margin:32px 0 12px; }
    .sechead h2 { font-size:13px; font-weight:600; margin:0; }
    .sechead .rule { flex:1; height:1px; background:var(--border-subtle); }
    .sechead .meta { font-family:var(--font-mono); font-size:10.5px; color:var(--text-tertiary); }
    .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(112px,1fr)); gap:1px; background:var(--border-subtle); border:1px solid var(--border-subtle); border-radius:6px; overflow:hidden; margin-top:16px; }
    .kpi { background:var(--bg-surface); padding:11px 13px; }
    .kpi .v { font-family:var(--font-mono); font-size:20px; font-weight:500; }
    .kpi .l { font-size:10.5px; color:var(--text-tertiary); text-transform:uppercase; letter-spacing:.07em; margin-top:2px; }
    .kpi.alert .v { color:var(--sev-high); } .kpi.good .v { color:var(--accent); }
    .reco { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:12px; }
    .card, .panel, .job-card { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:10px; }
    .panel { overflow:hidden; }
    .panel .ph { padding:16px; border-bottom:1px solid var(--border-subtle); display:flex; justify-content:space-between; align-items:center; gap:12px; }
    .panel .ph h2, .panel .ph h3 { margin:0; font-family:var(--font-mono); font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--text-tertiary); font-weight:500; }
    .panel .pb { padding:16px; }
    .card, .job-card { padding:16px; display:flex; flex-direction:column; gap:10px; }
    .card.hot { border-color:rgba(63,185,143,.35); box-shadow:inset 3px 0 0 var(--accent); }
    .card .top, .job-card header, .toolbar, .row, .job-flags, .job-meta, .filters, .tabs { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; flex-wrap:wrap; }
    .card h3, .job-card h3 { margin:0; font-size:15px; font-weight:600; line-height:1.3; overflow-wrap:anywhere; }
    .job-card strong, .panel h2, .panel h3, .sub { overflow-wrap:anywhere; }
    .co, .muted { color:var(--text-secondary); } .muted2 { color:var(--text-tertiary); }
    .why, .concerns-list, .reqlist { list-style:none; display:flex; flex-direction:column; gap:4px; padding:0; margin:0; font-size:12.5px; color:var(--text-secondary); }
    .why li { display:flex; gap:7px; line-height:1.45; } .why b { color:var(--accent); font-family:var(--font-mono); font-size:11px; flex:none; }
    .meta-line { font-family:var(--font-mono); font-size:10.5px; color:var(--text-tertiary); display:flex; gap:10px; flex-wrap:wrap; }
    .b { display:inline-flex; align-items:center; gap:4px; font-family:var(--font-mono); font-size:10px; font-weight:500; letter-spacing:.04em; text-transform:uppercase; padding:2px 6px; border-radius:3px; border:1px solid; white-space:nowrap; }
    .b.remote, .b.good { color:var(--accent); border-color:rgba(63,185,143,.4); background:var(--accent-subtle); }
    .b.hybrid { color:var(--sev-low); border-color:rgba(79,163,209,.35); background:rgba(79,163,209,.09); }
    .b.onsite, .b.stage, .b.unknown { color:var(--text-tertiary); border-color:var(--border-default); }
    .b.sp-yes { color:var(--positive); border-color:rgba(63,185,143,.45); background:var(--accent-subtle); }
    .b.sp-mid { color:var(--sev-low); border-color:rgba(79,163,209,.35); }
    .b.sp-none, .b.flag { color:var(--sev-critical); border-color:rgba(240,82,106,.45); background:rgba(240,82,106,.1); }
    .b.sp-unk, .b.warn { color:var(--sev-medium); border-color:rgba(227,192,74,.4); }
    .b.new { color:var(--accent); border-color:rgba(63,185,143,.45); }
    .score { display:inline-flex; align-items:center; gap:7px; } .score .n { font-family:var(--font-mono); font-size:13px; font-weight:700; min-width:24px; text-align:right; }
    .bar { width:56px; height:5px; border-radius:3px; background:var(--bg-overlay); overflow:hidden; } .bar i { display:block; height:100%; border-radius:3px; }
    .s90 .n, .s90 i { color:var(--positive); background:var(--positive); } .s75 .n, .s75 i { color:var(--accent); background:var(--accent); } .s60 .n, .s60 i { color:var(--sev-medium); background:var(--sev-medium); } .s0 .n, .s0 i { color:var(--text-tertiary); background:var(--text-tertiary); }
    .filter-btn, .subtab, .tab, .chip-toggle { font-family:var(--font-mono); font-size:10.5px; padding:4px 10px; border-radius:100px; border:1px solid var(--border-default); color:var(--text-secondary); background:transparent; }
    .filter-btn.active, .subtab.active, .tab.active, .chip-toggle.active { background:var(--accent-subtle); border-color:var(--accent); color:var(--accent); }
    .tblwrap { border:1px solid var(--border-subtle); border-radius:6px; overflow-x:auto; background:var(--bg-surface); }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    thead th { font-family:var(--font-mono); font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--text-tertiary); text-align:left; padding:9px 11px; background:var(--bg-raised); border-bottom:1px solid var(--border-default); white-space:nowrap; font-weight:500; }
    tbody td { padding:7px 11px; border-bottom:1px solid var(--border-subtle); vertical-align:middle; white-space:nowrap; }
    tbody tr:hover { background:var(--bg-raised); } tbody tr.sel { background:var(--accent-subtle); } tbody tr.excluded td { opacity:.42; } td.t { white-space:normal; min-width:190px; }
    .page-hero { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; }
    .hero-meta, .hero-actions, .hero-flags, .hero-stats, .detail-meta, .snapshot-chips, .acts, .acts2, .action-row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; min-width:0; }
    .acts, .acts2, .action-row { justify-content:flex-start; }
    .acts > *, .acts2 > *, .hero-actions > *, .action-row > * { min-width:0; }
    .hero-meta { margin-top:10px; }
    .hero-actions { align-items:flex-start; justify-content:flex-end; }
    .hero-actions .acts { display:flex; gap:6px; flex-wrap:wrap; }
    .job-card .hero-actions { margin-top:auto; gap:8px; justify-content:flex-start; }
    .job-card .hero-actions .btn { flex:1 1 120px; }
    .job-card .hero-actions .btn.primary { margin-left:0; }
    .hero-stack { display:grid; gap:12px; }
    .hero-subgrid { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(260px,.8fr); gap:12px; margin-top:16px; }
    .summary-card, .surface-block { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:10px; padding:14px 16px; }
    .summary-card h3, .surface-block h3 { margin:0 0 10px; font-family:var(--font-mono); font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--text-tertiary); }
    .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:10px; }
    .summary-metric { display:grid; gap:3px; padding:10px 12px; border:1px solid var(--border-subtle); border-radius:8px; background:var(--bg-base); }
    .summary-metric .label { font-family:var(--font-mono); font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--text-tertiary); }
    .summary-metric .value { font-size:16px; font-weight:600; letter-spacing:-.02em; }
    .summary-metric .meta { font-size:11.5px; color:var(--text-secondary); }
    .detail { display:grid; grid-template-columns:minmax(0,1fr) 380px; gap:24px; align-items:start; }
    .stack { display:grid; gap:16px; }
    .receipt { font-family:var(--font-mono); font-size:12px; line-height:1.85; }
    .receipt .hdr { display:flex; justify-content:space-between; align-items:baseline; gap:10px; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--text-tertiary); }
    .receipt .total-n { font-size:26px; font-weight:700; color:var(--positive); }
    .megabar { height:7px; background:var(--bg-overlay); border-radius:4px; overflow:hidden; margin:10px 0 14px; } .megabar i { display:block; height:100%; background:linear-gradient(90deg,var(--accent),var(--accent-hover)); }
    .rl { display:grid; grid-template-columns:38px 1fr; gap:10px; padding:4px 0; border-radius:4px; } .rl:hover { background:var(--bg-raised); } .rl .w { color:var(--positive); text-align:right; font-weight:500; } .rl .d { color:var(--text-secondary); display:flex; gap:9px; flex-wrap:wrap; } .rl .d em { font-style:normal; color:var(--text-tertiary); font-size:11px; }
    .rdiv { border-top:1px dashed var(--border-default); margin:9px 0; } .rtot { display:grid; grid-template-columns:38px 1fr auto; gap:10px; font-weight:700; }
    .careerops-line { margin-top:14px; padding-top:13px; border-top:1px solid var(--border-subtle); display:flex; justify-content:space-between; align-items:flex-end; gap:10px; }
    .careerops-line .value { font-size:18px; font-weight:700; color:var(--accent); }
    .jdbox, .code { background:var(--bg-base); border:1px solid var(--border-subtle); border-radius:6px; padding:16px; font-size:13px; color:var(--text-secondary); line-height:1.65; max-height:300px; overflow:auto; white-space:pre-wrap; }
    .jdbox p { margin:0; } .jdbox p + p { margin-top:10px; }
    .injbanner { display:flex; gap:10px; background:rgba(240,82,106,.09); border:1px solid rgba(240,82,106,.4); border-radius:6px; padding:11px; margin-bottom:11px; font-size:12.5px; color:var(--text-secondary); }
    .injbanner b { color:var(--sev-critical); font-family:var(--font-mono); font-size:10.5px; letter-spacing:.06em; text-transform:uppercase; display:block; margin-bottom:4px; }
    .timeline { font-family:var(--font-mono); font-size:11.5px; display:flex; flex-direction:column; gap:6px; } .timeline .r, .timeline-item { display:grid; grid-template-columns:74px 1fr auto; gap:10px; padding:6px 0; border-bottom:1px solid var(--border-subtle); align-items:baseline; } .timeline .r:last-child, .timeline-item:last-child { border-bottom:none; } .timeline .dt { color:var(--text-tertiary); } .timeline .who { color:var(--text-tertiary); font-size:10px; }
    .evidence-card { background:var(--bg-base); border:1px solid var(--border-subtle); border-radius:8px; padding:12px; display:grid; gap:7px; }
    .evidence-card .eyebrow { font-family:var(--font-mono); font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--text-tertiary); display:flex; justify-content:space-between; gap:8px; }
    .evidence-card .quote { color:var(--text-secondary); font-size:12.5px; line-height:1.55; }
    .board { display:grid; grid-template-columns:repeat(6,minmax(190px,1fr)); gap:12px; margin-top:16px; overflow-x:auto; } .column { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:6px; display:flex; flex-direction:column; min-height:340px; min-width:190px; } .colh { display:flex; align-items:center; justify-content:space-between; padding:10px 11px; border-bottom:1px solid var(--border-subtle); } .column-title, .column h3 { font-family:var(--font-mono); font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--text-secondary); } .column-count, .ct { font-family:var(--font-mono); font-size:10px; color:var(--text-tertiary); background:var(--bg-overlay); padding:1px 6px; border-radius:100px; } .column-list { padding:9px; display:flex; flex-direction:column; gap:8px; }
    .mini-card, .kc { background:var(--bg-raised); border:1px solid var(--border-subtle); border-left:2px solid var(--border-strong); border-radius:4px; padding:9px 10px; } .kc.hi { border-left-color:var(--accent); } .kc.risk { border-left-color:var(--sev-medium); } .kc .r { font-size:12.5px; font-weight:500; line-height:1.35; } .kc .c { font-family:var(--font-mono); font-size:10.5px; color:var(--text-tertiary); margin-top:3px; } .kc .f { display:flex; justify-content:space-between; align-items:center; margin-top:7px; gap:6px; } .kc .age { font-family:var(--font-mono); font-size:9.5px; color:var(--text-tertiary); }
    .colempty, .empty { padding:16px 11px; font-size:11.5px; color:var(--text-tertiary); line-height:1.5; border:1px dashed var(--border-default); border-radius:6px; }
    .studio { display:grid; grid-template-columns:240px minmax(0,1fr) 320px; gap:16px; margin-top:16px; align-items:start; }
    .studio > * { min-width:0; }
    .studio .stack { min-width:0; }
    .studio .panel { min-width:0; }
    .reqlist li { display:grid; grid-template-columns:14px 1fr; gap:8px; color:var(--text-secondary); line-height:1.45; } .reqlist .ok { color:var(--positive); font-family:var(--font-mono); } .reqlist .par { color:var(--sev-medium); font-family:var(--font-mono); } .reqlist .no { color:var(--sev-critical); font-family:var(--font-mono); }
    .tabs { gap:2px; border-bottom:1px solid var(--border-subtle); padding:0 12px; } .tab { border:none; border-bottom:2px solid transparent; border-radius:0; padding:10px 12px; margin-bottom:-1px; } .tab.active { color:var(--accent); border-bottom-color:var(--accent); background:none; }
    .tab-panel[hidden] { display:none !important; }
    .paper-wrap { background:linear-gradient(180deg, rgba(255,255,255,.02), transparent 22%); border-radius:8px; padding:4px; }
    .paper { background:#f7f7f4; color:#15181a; border-radius:3px; padding:22px 26px; font-family:Inter,system-ui,sans-serif; font-size:10px; line-height:1.55; min-height:420px; box-shadow:0 6px 24px rgba(0,0,0,.4); }
    .paper h4 { font-size:14px; margin:0 0 2px; } .paper .cl { font-family:var(--font-mono); font-size:7.5px; color:#4a5560; margin-bottom:9px; }
    .paper-body p { margin:0 0 8px; } .paper-body p:last-child { margin-bottom:0; }
    .paper-body h5 { margin:12px 0 6px; font-size:9px; font-family:var(--font-mono); letter-spacing:.12em; text-transform:uppercase; color:#2f3a42; border-bottom:1px solid #c9cfd4; padding-bottom:2px; }
    .paper-body ul { margin:4px 0 8px 16px; padding:0; } .paper-body li { margin-bottom:3px; }
    .paper-body .line-add { background:#d6f0e5; box-shadow:0 0 0 2px #d6f0e5; }
    .code-pane { background:var(--bg-base); border:1px solid var(--border-subtle); border-radius:6px; padding:16px; font-family:var(--font-mono); font-size:11px; line-height:1.7; white-space:pre-wrap; color:var(--text-secondary); min-height:420px; }
    .diff-list { display:grid; gap:10px; }
    .diff-card { border:1px solid var(--border-subtle); border-radius:8px; background:var(--bg-base); padding:12px; display:grid; gap:8px; }
    .diff-card .before { color:var(--text-tertiary); text-decoration:line-through; font-size:12px; } .diff-card .after { color:var(--text-primary); font-size:12.5px; }
    .pagemark { display:flex; align-items:center; gap:9px; margin-top:9px; font-family:var(--font-mono); font-size:9.5px; color:var(--text-tertiary); } .pagemark .ln { flex:1; height:1px; background:var(--border-default); }
    .fit { display:flex; flex-direction:column; gap:3px; } .fitrow { display:grid; grid-template-columns:1fr auto; gap:10px; font-family:var(--font-mono); font-size:11.5px; padding:3px 0; } .fitrow .lbl { color:var(--text-secondary); } .fitrow .val { color:var(--positive); } .fitrow .val.bad { color:var(--sev-high); }
    .delta { display:flex; align-items:baseline; gap:9px; font-family:var(--font-mono); flex-wrap:wrap; } .delta .old { font-size:15px; color:var(--text-tertiary); text-decoration:line-through; } .delta .arrow { color:var(--text-tertiary); } .delta .newv { font-size:28px; font-weight:700; color:var(--positive); } .delta .plus { font-size:11px; color:var(--accent); background:var(--accent-subtle); padding:2px 7px; border-radius:100px; }
    .kwgroup { margin-top:16px; } .kwtitle { font-family:var(--font-mono); font-size:9.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--text-tertiary); margin-bottom:7px; display:flex; justify-content:space-between; } .kw { display:flex; gap:8px; align-items:flex-start; padding:8px; border-radius:4px; font-size:12.5px; line-height:1.4; background:rgba(255,255,255,.01); } .kw.present .mk { color:var(--positive); } .kw.safe .mk { color:var(--sev-low); } .kw.block { background:rgba(240,82,106,.07); border:1px solid rgba(240,82,106,.22); } .kw.block .mk { color:var(--sev-critical); } .kw .bk { display:block; font-family:var(--font-mono); font-size:10px; color:var(--text-tertiary); margin-top:2px; }
    .sugg { background:var(--bg-base); border:1px solid var(--border-subtle); border-radius:6px; padding:11px; margin-bottom:9px; } .sugg .kd { font-family:var(--font-mono); font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); margin-bottom:7px; display:flex; justify-content:space-between; gap:8px; } .sugg .bef { font-size:12px; color:var(--text-tertiary); text-decoration:line-through; line-height:1.5; } .sugg .aft { font-size:12.5px; color:var(--text-primary); line-height:1.5; margin-top:5px; } .sugg .ev2 { font-family:var(--font-mono); font-size:10px; color:var(--text-tertiary); margin-top:7px; padding-top:7px; border-top:1px solid var(--border-subtle); line-height:1.6; } .sugg .acts2 { display:flex; gap:6px; margin-top:9px; flex-wrap:wrap; }
    .variant-grid, .event-feed { display:grid; gap:12px; }
    .variant-grid { grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); align-items:stretch; }
    .variant-grid .job-card { min-height:180px; }
    .variant-card-top { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:flex-start; }
    .variant-card-top .score { justify-self:end; }
    .event-feed { max-height:540px; overflow:auto; padding-right:4px; }
    .event-card { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:8px; padding:10px 12px; display:grid; grid-template-columns:minmax(150px,.35fr) minmax(0,1fr); gap:6px 12px; align-items:start; }
    .event-card strong { overflow-wrap:anywhere; }
    .event-card .event-meta { grid-column:1; font-size:10.5px; line-height:1.45; }
    .event-card .event-detail { grid-column:2; grid-row:1 / span 2; min-width:0; overflow-wrap:anywhere; line-height:1.5; }
    .note { font-size:11.5px; color:var(--text-tertiary); line-height:1.55; margin-top:16px; border-left:2px solid var(--border-default); padding-left:10px; }
    @media (max-width:1300px) {
      .detail, .hero-subgrid { grid-template-columns:1fr; }
      .studio { grid-template-columns:minmax(220px,.36fr) minmax(0,1fr); }
      .studio > .stack:last-child { grid-column:1 / -1; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
    }
    @media (max-width:900px) {
      .app-shell { grid-template-columns:1fr; }
      .sidebar { position:sticky; top:0; z-index:50; height:auto; max-height:none; border-right:0; border-bottom:1px solid var(--border-subtle); padding:10px 12px; overflow:visible; }
      .brand { padding:0 2px 8px; }
      .nav-group { display:flex; gap:6px; overflow-x:auto; padding-bottom:2px; scrollbar-width:thin; }
      .nav-label { display:none; }
      .nav-btn { flex:0 0 auto; width:auto; border:1px solid var(--border-default); border-radius:999px; border-left-width:1px; padding:6px 10px; background:var(--bg-base); }
      .nav-btn.active { border-color:var(--accent); background:var(--accent-subtle); }
      .content { min-width:0; }
      .topbar { position:static; }
      .board { grid-template-columns:repeat(6,240px); }
      .event-card { grid-template-columns:1fr; }
      .event-card .event-meta, .event-card .event-detail { grid-column:auto; grid-row:auto; }
    }
    @media (max-width:760px) {
      .topbar { padding:12px 16px; flex-direction:column; align-items:stretch; }
      .search { max-width:none; width:100%; }
      .topbar-right, .hero-actions, .hero-actions .acts { width:100%; justify-content:flex-start; }
      .main { padding:16px; }
      .page-hero { gap:12px; }
      .reco, .summary-grid, .variant-grid, .studio, .studio > .stack:last-child { grid-template-columns:1fr; }
      .panel .ph { align-items:flex-start; flex-wrap:wrap; }
      .tabs { overflow-x:auto; flex-wrap:nowrap; justify-content:flex-start; }
      .tab { flex:0 0 auto; }
      .paper-wrap { margin:0 -4px; padding:0; overflow-x:auto; }
      .paper { min-height:320px; min-width:560px; padding:18px 20px; }
      .code-pane, .jdbox { min-height:300px; max-height:56vh; }
      .timeline .r, .timeline-item { grid-template-columns:1fr; gap:2px; }
      .rtot { grid-template-columns:38px 1fr; }
      .rtot span:last-child { grid-column:2; }
      .careerops-line { align-items:flex-start; flex-direction:column; }
      .btn { flex:0 0 auto; }
    }
    @media (max-width:480px) {
      html, body { font-size:14px; }
      .main { padding:12px; }
      .topbar { padding:10px 12px; }
      .summary-metric { padding:9px 10px; }
      .panel .pb, .panel .ph, .card, .job-card { padding:12px; }
      .variant-grid .job-card { min-height:0; }
      .hero-actions .acts .btn, .hero-actions > .btn, .hero-actions > a.btn, .topbar-right .btn { flex:1 1 140px; text-align:center; }
      .sechead { margin:24px 0 10px; }
    }
  </style>
</head>
<body>
  <div class=\"app-shell\">
    <aside class=\"sidebar\">
      <div class=\"brand\"><div class=\"brand-dot\"></div><div><b>Job Radar</b><span>SOC · St. Louis</span></div></div>
      <nav class=\"nav-group\" id=\"primary-nav\"></nav>
    </aside>
    <div class=\"content\">
      <div class=\"topbar\">
        <div class=\"search\"><span>⌕</span><input id=\"global-search\" placeholder=\"Search jobs, companies, contacts\" /><span class=\"search-kbd\">⌘K</span></div>
        <div class=\"topbar-right\">
          <span class=\"pill\" id=\"scan-pill\"><span class=\"live-dot\"></span>Scan status</span>
          <button class=\"btn\" type=\"button\">Density</button>
          <form method=\"post\" action=\"/auth/logout\"><button class=\"btn\" type=\"submit\">Logout</button></form>
        </div>
      </div>
      <main class=\"main\">
        <section id=\"today\" class=\"section active\"></section>
        <section id=\"jobs\" class=\"section\"></section>
        <section id=\"pipeline\" class=\"section\"></section>
        <section id=\"resume\" class=\"section\"></section>
        <section id=\"applications\" class=\"section\"></section>
        <section id=\"interviews\" class=\"section\"></section>
        <section id=\"companies\" class=\"section\"></section>
        <section id=\"contacts\" class=\"section\"></section>
        <section id=\"documents\" class=\"section\"></section>
        <section id=\"analytics\" class=\"section\"></section>
        <section id=\"automation\" class=\"section\"></section>
        <section id=\"settings\" class=\"section\"></section>
        <section id=\"detail\" class=\"section\"></section>
      </main>
    </div>
  </div>
  <script>
    const INITIAL_PATH = "__INITIAL_PATH__";
    const sections = [
      { id: 'today', label: 'Today', path: '/' },
      { id: 'jobs', label: 'Jobs', path: '/jobs' },
      { id: 'pipeline', label: 'Pipeline', path: '/pipeline' },
      { id: 'resume', label: 'Resume Studio', path: '/resume' },
      { id: 'applications', label: 'Applications', path: '/applications' },
      { id: 'interviews', label: 'Interviews', path: '/interviews' },
      { id: 'companies', label: 'Companies', path: '/companies' },
      { id: 'contacts', label: 'Contacts', path: '/contacts' },
      { id: 'documents', label: 'Documents', path: '/documents' },
      { id: 'analytics', label: 'Analytics', path: '/analytics' },
      { id: 'automation', label: 'Automation', path: '/automation' },
      { id: 'settings', label: 'Settings', path: '/settings' },
    ];

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>\"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;' }[c]));
    }

    function fmtMaybe(value, fallback = '—') {
      return value === null || value === undefined || value === '' ? fallback : String(value);
    }

    function fmtTime(value) {
      if (!value) return '—';
      const d = new Date(value);
      return isNaN(d.getTime()) ? value : d.toLocaleString();
    }

    function fmtDateShort(value) {
      if (!value) return '—';
      const d = new Date(value);
      return isNaN(d.getTime()) ? value : d.toLocaleDateString(undefined, { month:'short', day:'numeric' });
    }

    function nl2br(value) {
      return escapeHtml(value || '').replace(/\\n/g, '<br>');
    }

    function paragraphize(value) {
      const safe = escapeHtml(value || '');
      if (!safe.trim()) return '<p>No content available.</p>';
      return safe.split(/\\n\\s*\\n/).map((block) => {
        const trimmed = block.trim();
        if (!trimmed) return '';
        if (/^[-*]\\s+/m.test(trimmed)) {
          const items = trimmed.split(/\\n/).filter(Boolean).map((line) => `<li>${line.replace(/^[-*]\\s+/, '')}</li>`).join('');
          return `<ul>${items}</ul>`;
        }
        if (/^##\\s+/.test(trimmed)) {
          const lines = trimmed.split(/\\n/);
          const heading = lines.shift().replace(/^##\\s+/, '');
          const body = lines.join('\\n').trim();
          return `<h5>${heading}</h5>${body ? `<p>${body.replace(/\\n/g, '<br>')}</p>` : ''}`;
        }
        if (/^[A-Z][A-Z &/+:-]{2,}$/.test(trimmed) && trimmed.length <= 48) {
          return `<h5>${trimmed}</h5>`;
        }
        return `<p>${trimmed.replace(/\\n/g, '<br>')}</p>`;
      }).join('');
    }

    function prettyLabel(value) {
      return String(value || '').replace(/[_-]+/g, ' ').replace(/\\b\\w/g, (c) => c.toUpperCase());
    }

    function parseMaybeJson(value) {
      if (!value || typeof value !== 'string') return value;
      try { return JSON.parse(value); } catch (_) { return value; }
    }

    function sanitizeDetail(detail) {
      const raw = parseMaybeJson(detail);
      if (!raw || typeof raw !== 'object') return raw;
      const clone = Array.isArray(raw) ? [...raw] : { ...raw };
      delete clone.file_path;
      delete clone.source_path;
      delete clone.content_text;
      return clone;
    }

    function renderDetailPayload(detail) {
      const clean = sanitizeDetail(detail);
      if (clean === null || clean === undefined || clean === '') return 'No additional detail';
      if (typeof clean === 'string') return escapeHtml(clean);
      const entries = Object.entries(clean);
      if (!entries.length) return 'No additional detail';
      return entries.slice(0, 4).map(([key, val]) => `${escapeHtml(prettyLabel(key))}: ${escapeHtml(typeof val === 'object' ? JSON.stringify(val) : String(val))}`).join(' · ');
    }

    function renderEventCard(evt) {
      return `<div class="event-card"><strong>${escapeHtml(evt.event_type || 'resume.event')}</strong><div class="muted mono event-meta">${fmtTime(evt.occurred_at)} · ${escapeHtml(evt.actor || 'system')}</div><div class="muted2 event-detail">${renderDetailPayload(evt.detail)}</div></div>`;
    }

    function latestAtsAnalysis(variant) {
      const analyses = variant?.ats_analyses || [];
      if (!analyses.length) return null;
      return [...analyses].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0];
    }

    function renderBreakdownRows(job) {
      const lines = job.score_breakdown || [];
      if (!lines.length) return '<div class="rl"><span class="w">+0</span><span class="d">No score breakdown stored.</span></div>';
      return lines.slice(0, 10).map((line) => {
        const earned = Number(line.earned ?? line.score ?? 0);
        const weight = line.weight ? `weight ${line.weight}` : 'stored rationale';
        const label = prettyLabel(line.dimension || line.label || 'score factor');
        const evidence = line.evidence || line.reason || '';
        return `<div class="rl"><span class="w">${earned >= 0 ? '+' : ''}${Math.round(earned)}</span><span class="d">${escapeHtml(label)} <em>${escapeHtml(evidence || weight)}</em></span></div>`;
      }).join('');
    }

    function renderInlineError(targetId, title, error) {
      const target = document.getElementById(targetId) || document.querySelector('.main') || document.body;
      target.innerHTML = `<div class="panel"><div class="pb"><h2>${escapeHtml(title)}</h2><div class="code">${escapeHtml(error?.message || error || 'Unknown error')}</div><button class="btn" type="button" onclick="location.reload()">Retry</button></div></div>`;
    }

    function bindJobLinks(state) {
      for (const link of document.querySelectorAll('[data-job-link]')) {
        link.addEventListener('click', async (event) => {
          event.preventDefault();
          try {
            const job = await fetchJson(`/api/v1/jobs/${link.dataset.jobLink}`, { timeoutMs: 10000 });
            history.replaceState({}, '', `/jobs/${link.dataset.jobLink}`);
            renderDetail(job);
            showSection('detail');
            renderPrimaryNav('detail', state);
          } catch (error) {
            renderInlineError('detail', 'Job detail could not be loaded', error);
            showSection('detail');
          }
        });
      }
    }


    function agoLabel(value) {
      if (!value) return '—';
      const ms = Date.now() - new Date(value).getTime();
      if (!isFinite(ms)) return fmtTime(value);
      const h = Math.floor(ms / 3600000);
      if (h < 1) return 'now';
      if (h < 24) return `${h}h`;
      const d = Math.floor(h / 24);
      return `${d}d`;
    }

    function scoreClass(value) {
      const n = Number(value || 0);
      if (n >= 85) return 's90';
      if (n >= 75) return 's75';
      if (n >= 60) return 's60';
      return 's0';
    }

    function scoreWidget(value) {
      const n = Number(value || 0);
      const cls = scoreClass(n);
      return `<span class="score ${cls}"><span class="bar"><i style="width:${Math.max(2, Math.min(100, n))}%"></i></span><span class="n">${Math.round(n)}</span></span>`;
    }

    function workModeBadge(job) {
      const mode = job.location?.work_mode || '';
      const label = job.location?.raw || 'Unknown';
      if (mode === 'remote') return `<span class="b remote">${escapeHtml(label)}</span>`;
      if (mode === 'hybrid') return `<span class="b hybrid">${escapeHtml(label)}</span>`;
      return `<span class="b onsite">${escapeHtml(label)}</span>`;
    }

    function sponsorshipDerivation(job, ev = null) {
      const conf = Math.round(Number(job?.sponsorship?.confidence || 0) * 100);
      const cls = job?.sponsorship?.class || 'Not stated';
      const text = ev?.evidence_text || ev?.quoted_span || job?.sponsorship?.evidence_summary || '';
      const fy = (text.match(/FY\s?\d{4}/i) || ev?.source_as_of?.match(/FY\s?\d{4}/i) || [null])[0];
      const approvals = (text.match(/(\d+)\s+(?:initial\s+)?approvals?/i) || [null, null])[1];
      if (approvals && fy) return `Confidence ${conf}% from ${approvals} H-1B approvals in ${fy}; ${cls} employers map to this confidence band.`;
      if (fy) return `Confidence ${conf}% from ${fy} sponsorship history and employer signals.`;
      if (conf) return `Confidence ${conf}% from stored sponsorship evidence and employer signals.`;
      return 'No sponsorship confidence derivation is available yet.';
    }

    function sourceYearLabel(ev) {
      const text = `${ev?.evidence_text || ''} ${ev?.quoted_span || ''} ${ev?.source_as_of || ''}`;
      const fy = (text.match(/FY\s?\d{4}/i) || [null])[0];
      return fy || 'Source year unknown';
    }

    function sponsorshipBadge(job) {
      const cls = String(job.sponsorship?.class || 'unknown').toLowerCase();
      const conf = Number(job.sponsorship?.confidence || 0);
      const title = escapeHtml(sponsorshipDerivation(job));
      if (cls.includes('likely') || cls.includes('yes') || cls.includes('support')) return `<span class="b sp-yes" title="${title}">Sponsor likely ${Math.round(conf*100)}%</span>`;
      if (cls.includes('possible') || cls.includes('historically')) return `<span class="b sp-mid" title="${title}">Possible ${Math.round(conf*100)}%</span>`;
      if (cls.includes('no') || cls.includes('clearance') || cls.includes('citizen')) return `<span class="b sp-none" title="${title}">${escapeHtml(job.sponsorship?.class || 'No sponsor')}</span>`;
      return `<span class="b sp-unk" title="${title}">${escapeHtml(job.sponsorship?.class || 'Not stated')}</span>`;
    }

    function sourceShort(job) {
      const url = job.application_url || job.source_url || '';
      if (url.includes('greenhouse')) return 'GH';
      if (url.includes('lever')) return 'LV';
      if (url.includes('ashby')) return 'AB';
      if (url.includes('workday')) return 'WD';
      return 'WEB';
    }

    function locationShort(job) {
      return job.location?.raw || 'Unknown';
    }

    function topReasons(job, count = 3) {
      const reasons = (job.fit_reasons || []).slice(0, count).map((reason) => String(reason));
      if (reasons.length) return reasons;
      return (job.score_breakdown || []).slice(0, count).map((line) => line?.evidence || prettyLabel(line?.dimension || 'score factor'));
    }

    function concernText(job) {
      return (job.concerns || []).filter(Boolean);
    }

    function renderActionButtons(job) {
      return `<div class="acts"><a class="btn primary" href="/resume/${escapeHtml(job.id)}">Tailor resume</a>${job.application_url ? `<a class="btn" href="${escapeHtml(job.application_url)}" target="_blank" rel="noreferrer">Open original</a>` : ''}<button class="btn" data-job-link="${escapeHtml(job.id)}">View details</button></div>`;
    }

    function careerOpsState(job) {
      const value = job?.scores?.career_ops;
      const report = job?.application?.careerops_tracker_num;
      if (value !== null && value !== undefined && value !== '') {
        return { value: fmtMaybe(value), label: '1.0–5.0', state: 'scored', help: report ? `Report #${report}` : 'Career-Ops evaluation attached' };
      }
      if (job?.career_ops_error || job?.application?.careerops_error) return { value: 'Error', label: 'Could not evaluate', state: 'failed', help: job.career_ops_error || job.application.careerops_error };
      if (['Rejected', 'Withdrawn', 'Archived'].includes(job?.status)) return { value: 'N/A', label: 'Not applicable', state: 'na', help: 'Excluded/closed jobs are not sent for Career-Ops evaluation.' };
      return { value: 'Pending', label: 'Evaluating…', state: 'pending', help: 'Career-Ops runs after discovery; retry from automation if it stays pending.' };
    }

    function careerOpsCell(job) {
      const co = careerOpsState(job);
      const cls = co.state === 'scored' ? 'sp-yes' : co.state === 'failed' ? 'sp-none' : co.state === 'na' ? 'stage' : 'sp-mid';
      return `<span class="b ${cls}" title="${escapeHtml(co.help)}">${escapeHtml(co.value)}</span>`;
    }

    function scorePill(job) {
      const personal = job?.scores?.personal;
      const co = careerOpsState(job);
      const tier = job?.scores?.tier ?? job?.tier ?? '—';
      return `<span class=\"pill\" title=\"${escapeHtml(co.help)}\">Score ${fmtMaybe(personal)} · C-Ops ${escapeHtml(co.value)} · Tier ${tier}</span>`;
    }

    function jobFlags(job) {
      const loc = job.location?.raw ?? job.location_raw ?? 'Unknown';
      const sponsorship = job.sponsorship?.class ?? 'unknown';
      const live = job.liveness_status ?? 'Unknown';
      return `
        <div class=\"job-flags\">
          <span class=\"chip\">${escapeHtml(loc)}</span>
          <span class=\"chip\">${escapeHtml(sponsorship)}</span>
          <span class=\"chip\">${escapeHtml(live)}</span>
          ${job.application_url ? `<a class=\"chip\" href=\"${escapeHtml(job.application_url)}\" target=\"_blank\" rel=\"noreferrer\">Open original job</a>` : ''}
        </div>`;
    }

    function isAbortError(error) {
      return error?.name === 'AbortError' || String(error?.message || error).toLowerCase().includes('abort') || String(error?.message || error).toLowerCase().includes('timed out loading');
    }

    async function fetchJson(path, options = {}) {
      const timeoutMs = options.timeoutMs || 0;
      const controller = timeoutMs ? new AbortController() : null;
      const timer = timeoutMs ? setTimeout(() => controller.abort(new DOMException(`Timed out loading ${path}`, 'AbortError')), timeoutMs) : null;
      try {
        const res = await fetch(path, { credentials: 'same-origin', signal: controller ? controller.signal : undefined });
        if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
        return await res.json();
      } catch (error) {
        if (isAbortError(error)) throw new Error(`Timed out loading ${path}. Showing cached/partial dashboard state; retry or refresh if this panel is still needed.`);
        throw error;
      } finally {
        if (timer) clearTimeout(timer);
      }
    }

    async function fetchJsonOptional(path, fallback, timeoutMs = 3500) {
      try {
        return await fetchJson(path, { timeoutMs });
      } catch (error) {
        if (!isAbortError(error)) console.warn('Optional dashboard request failed', path, error?.message || error);
        return fallback;
      }
    }

    async function postJson(path, body = {}) {
      const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify(body) });
      if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
      return await res.json().catch(() => ({}));
    }

    function scanPill(state) {
      const scan = state?.status?.latest_scan || state?.digest?.latest_scan || {};
      const status = String(scan.status || state?.status?.health || state?.health?.status || 'loading').toLowerCase();
      if (status.includes('running')) return '<span class="live-dot"></span>Scan in progress';
      if (status.includes('loading') && !scan.started_at && !scan.completed_at) return '<span class="live-dot" style="background:var(--text-tertiary)"></span>Scan idle';
      if (status.includes('fail') || status.includes('error')) return `<span class="live-dot" style="background:var(--sev-medium)"></span>Scan failed — retry`;
      const when = scan.completed_at || scan.started_at || state?.health?.checks?.scheduler?.last_scan_at;
      return `<span class="live-dot" style="background:var(--text-tertiary)"></span>Last scan: ${agoLabel(when)}`;
    }

    function loadingRows(colspan, label = 'Loading…') {
      return `<tr><td colspan="${colspan}" class="muted"><div class="empty">${escapeHtml(label)}</div></td></tr>`;
    }

    function renderPrimaryNav(activeId, state = null) {
      const counts = {
        today: fmtMaybe(state?.digest?.new_jobs_count, 0),
        jobs: fmtMaybe(state?.jobs?.total, 0),
        pipeline: fmtMaybe(state?.applications?.total, 0),
        resume: fmtMaybe(state?.resumeWorkspace?.variants?.length || state?.resumeBases?.total, 0),
        applications: fmtMaybe(state?.applications?.total, 0),
        interviews: fmtMaybe(state?.interviews?.total, 0),
        companies: fmtMaybe(state?.companies?.total, 0),
        contacts: fmtMaybe(state?.contacts?.total, 0),
        documents: fmtMaybe(state?.documents?.total, 0),
        analytics: '',
        automation: fmtMaybe(state?.runs?.items?.length, 0),
        settings: '',
      };
      const groups = [
        ['Search', ['today', 'jobs', 'pipeline', 'resume', 'applications', 'interviews']],
        ['Reference', ['companies', 'contacts', 'documents']],
        ['System', ['analytics', 'automation', 'settings']],
      ];
      document.getElementById('primary-nav').innerHTML = groups.map(([label, ids]) => `<div><div class="nav-label">${label}</div>${ids.map((id) => { const section = sections.find((s) => s.id === id); return `<button class="nav-btn ${id === activeId ? 'active' : ''}" data-target="${id}" data-path="${section.path}"><span>${section.label}</span><span class="cnt">${counts[id] ?? ''}</span></button>`; }).join('')}</div>`).join('');
      for (const btn of document.querySelectorAll('.nav-btn')) {
        btn.addEventListener('click', () => {
          const id = btn.dataset.target;
          history.replaceState({}, '', btn.dataset.path || '/');
          showSection(id);
        });
      }
    }

    function showSection(id) {
      for (const el of document.querySelectorAll('.section')) el.classList.remove('active');
      const target = document.getElementById(id) || document.getElementById('today');
      target.classList.add('active');
      renderPrimaryNav(id, window.__JR_STATE || null);
      ensureSectionData(id).catch((error) => console.debug('Section refresh skipped', id, error?.message || error));
    }

    async function ensureSectionData(id) {
      const state = window.__JR_STATE;
      if (!state) return;
      if (id === 'companies' && state.companies?.status === 'loading') {
        state.companies = await fetchJsonOptional('/api/v1/companies', { items: [], total: 0 }, 8000);
        renderCompanies(state); renderPrimaryNav(id, state);
      } else if (id === 'contacts' && state.contacts?.status === 'loading') {
        state.contacts = await fetchJsonOptional('/api/v1/contacts', { items: [], total: 0 }, 8000);
        renderContacts(state); renderPrimaryNav(id, state);
      } else if (id === 'documents' && state.documents?.status === 'loading') {
        state.documents = await fetchJsonOptional('/api/v1/documents', { items: [], total: 0 }, 8000);
        renderDocuments(state); renderPrimaryNav(id, state);
      } else if (id === 'interviews' && state.interviews?.status === 'loading') {
        state.interviews = await fetchJsonOptional('/api/v1/interviews', { items: [], total: 0 }, 8000);
        renderInterviews(state); renderPrimaryNav(id, state);
      } else if (id === 'automation' && state.runs?.status === 'loading') {
        state.runs = await fetchJsonOptional('/api/v1/automation/runs?limit=10', { items: [], total: 0 }, 8000);
        state.failures = await fetchJsonOptional('/api/v1/automation/failures', { items: [], total: 0 }, 8000);
        renderAutomation(state); renderPrimaryNav(id, state);
      }
    }

    function renderToday(data) {
      const topJobs = [...(data.digest.top_jobs || data.jobs.items || [])].slice(0, 3);
      const followups = data.digest.followups || [];
      const strongMatches = (data.jobs.items || []).filter((j) => Number(j.scores?.personal || 0) >= 75).length;
      const sponsorFriendly = (data.jobs.items || []).filter((j) => !String(j.sponsorship?.class || '').toLowerCase().includes('no')).length;
      document.getElementById('today').innerHTML = `
        <div class="h1">Today</div>
        <div class="sub">${new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' })} · last scan ${fmtTime(data.digest.latest_scan?.started_at)} · next ${fmtTime(data.status.next_scan_at || data.health.checks?.scheduler?.next_scan_at)} · ${fmtMaybe(data.digest.new_jobs_count, 0)} new since last visit</div>
        <div class="kpis">
          <div class="kpi good"><div class="v">${fmtMaybe(data.digest.new_jobs_count, 0)}</div><div class="l">New today</div></div>
          <div class="kpi good"><div class="v">${strongMatches}</div><div class="l">Strong match</div></div>
          <div class="kpi"><div class="v">${(data.jobs.items || []).filter((j) => ['Discovered','Reviewing','Saved'].includes(j.status)).length}</div><div class="l">Needs review</div></div>
          <div class="kpi"><div class="v">${fmtMaybe(data.applications.total, 0)}</div><div class="l">Active</div></div>
          <div class="kpi"><div class="v">${fmtMaybe(data.interviews.total, 0)}</div><div class="l">Interviews</div></div>
          <div class="kpi alert"><div class="v">${fmtMaybe(data.digest.followups_due_count, 0)}</div><div class="l">Follow up</div></div>
          <div class="kpi"><div class="v">${sponsorFriendly}</div><div class="l">Sponsor-ok</div></div>
          <div class="kpi"><div class="v">${fmtMaybe(data.runs.items?.length, 0)}</div><div class="l">Automation</div></div>
        </div>
        <div class="sechead"><h2>Recommended today</h2><div class="rule"></div><span class="meta">match · freshness · sponsorship</span></div>
        <div class="reco">${topJobs.length ? topJobs.map((job) => `
          <article class="card ${Number(job.scores?.personal || 0) >= 82 ? 'hot' : ''}">
            <div class="top"><div><h3>${escapeHtml(job.title)}</h3><div class="co">${escapeHtml(job.company?.name || 'Unknown company')} · ${escapeHtml(locationShort(job))}</div></div>${scoreWidget(job.scores?.personal)}</div>
            <div class="row">${workModeBadge(job)}${sponsorshipBadge(job)}<span class="b new">New · ${agoLabel(job.discovered_at || job.created_at)}</span></div>
            <ul class="why">${topReasons(job).map((reason, i) => `<li><b>+${Math.max(4, 16 - i*4)}</b>${escapeHtml(reason)}</li>`).join('') || '<li><b>+8</b>Prioritized from current score and workflow state.</li>'}</ul>
            <div class="meta-line"><span>${escapeHtml(job.salary_text || 'Not disclosed')}</span><span>${sourceShort(job)}</span><span>C-Ops ${escapeHtml(careerOpsState(job).value)}</span></div>
            ${renderActionButtons(job)}
          </article>`).join('') : '<div class="empty">No jobs are currently available in the digest.</div>'}</div>
        <div class="sechead"><h2>Follow-up required</h2><div class="rule"></div><span class="meta">${followups.length} due</span></div>
        <div class="tblwrap"><table><thead><tr><th>Company</th><th>Role</th><th>Applied</th><th>Silent</th><th>Next action</th><th>Contact</th><th></th></tr></thead><tbody>${followups.length ? followups.map((item) => `<tr><td><span class="mono">${escapeHtml(item.company || '—')}</span></td><td class="t">${escapeHtml(item.title || '—')}</td><td class="mono">${fmtTime(item.applied_at || item.created_at)}</td><td class="mono">${item.follow_up_at ? agoLabel(item.follow_up_at) : '—'}</td><td>${escapeHtml(item.next_action || 'No next action')}</td><td class="mono">${escapeHtml(item.contact_name || '—')}</td><td><button class="btn">Draft</button></td></tr>`).join('') : '<tr><td colspan="7" class="muted">No follow-ups are due right now.</td></tr>'}</tbody></table></div>
        <div class="sechead"><h2>Search health</h2><div class="rule"></div><span class="meta">live</span></div>
        <div class="meta-line" style="font-size:11.5px"><span>${fmtTime(data.digest.latest_scan?.started_at)} · ${fmtMaybe(data.companies.total, 0)} companies · ${fmtMaybe(data.digest.new_jobs_count, 0)} added</span><span>c-ops ${escapeHtml(data.health.checks?.careerops?.status || 'unknown')}</span><span>Hermes gateway ${escapeHtml(data.health.status || 'unknown')}</span><span>Eval queue ${fmtMaybe(data.queue.total, 0)}</span></div>`;
    }

    function renderJobs(data, activeView = 'table', activeFilter = 'all') {
      const filters = [['all','All active'],['needs','Needs action'],['score75','Score 75+'],['remote','Remote'],['stl','St. Louis'],['closed','Closed']];
      const rows = (data.jobs.items || []).filter((job) => passesFilter(job, activeFilter));
      const stageOrder = data.pipeline.stage_order || [];
      const columns = data.pipeline.columns || {};
      let body = '';
      if (activeView === 'board') {
        body = `<div class="board">${stageOrder.map((stage) => { const items = (columns[stage] || []).slice(0, 4); const overflow = Math.max(0, (columns[stage] || []).length - items.length); return `<div class="column"><div class="colh"><span class="column-title">${escapeHtml(stage)}</span><span class="ct">${(columns[stage] || []).length}</span></div><div class="column-list">${items.length ? items.map((item) => `<div class="kc ${Number(item.personal_score || 0) >= 80 ? 'hi' : Number(item.personal_score || 0) < 70 ? 'risk' : ''}"><div class="r"><a href="/jobs/${escapeHtml(item.id)}" data-job-link="${escapeHtml(item.id)}">${escapeHtml(item.title)}</a></div><div class="c">${escapeHtml(item.company)}</div><div class="f"><span class="b stage">${escapeHtml(item.liveness_status || 'Unknown')}</span><span class="age">${fmtMaybe(item.personal_score, '—')}</span></div></div>`).join('') : '<div class="colempty">No jobs in this stage.</div>'}${overflow ? `<div class="colempty">${overflow} more — open List view</div>` : ''}</div></div>`; }).join('')}</div>`;
      } else if (activeView === 'cards') {
        body = `<div class="reco">${rows.length ? rows.slice(0, 18).map((job) => `<article class="card ${Number(job.scores?.personal || 0) >= 82 ? 'hot' : ''}"><div class="top"><div><h3><a href="/jobs/${escapeHtml(job.id)}" data-job-link="${escapeHtml(job.id)}">${escapeHtml(job.title)}</a></h3><div class="co">${escapeHtml(job.company?.name || '—')}</div></div>${scoreWidget(job.scores?.personal)}</div><div class="row">${workModeBadge(job)}${sponsorshipBadge(job)}</div>${renderActionButtons(job)}</article>`).join('') : '<div class="empty">No jobs match this filter.</div>'}</div>`;
      } else {
        body = `<div class="tblwrap"><table><thead><tr><th style="width:26px">☆</th><th>Company</th><th>Title</th><th>Location</th><th>Salary</th><th>Match</th><th>C-Ops</th><th>Sponsorship</th><th>Posted</th><th>Src</th><th>Status</th><th style="width:26px"></th></tr></thead><tbody>${rows.length ? rows.map((job, idx) => `<tr class="${idx === 0 ? 'sel' : ''} ${['Rejected','Withdrawn','Archived'].includes(job.status) ? 'excluded' : ''}"><td>☆</td><td><span class="mono">${escapeHtml(job.company?.name || '—')}</span></td><td class="t"><b><a href="/jobs/${escapeHtml(job.id)}" data-job-link="${escapeHtml(job.id)}">${escapeHtml(job.title)}</a></b></td><td>${workModeBadge(job)}</td><td class="mono">${escapeHtml(job.salary_text || 'Not disclosed')}</td><td>${scoreWidget(job.scores?.personal)}</td><td>${careerOpsCell(job)}</td><td>${sponsorshipBadge(job)}</td><td class="mono">${agoLabel(job.discovered_at || job.created_at)}</td><td class="mono">${sourceShort(job)}</td><td><span class="b stage">${escapeHtml(job.status || '—')}</span></td><td>⋯</td></tr>`).join('') : '<tr><td colspan="12" class="muted">No jobs match this filter.</td></tr>'}</tbody></table></div>`;
      }
      document.getElementById('jobs').innerHTML = `<div class="h1">Jobs</div><div class="sub">${fmtMaybe(data.jobs.total, 0)} tracked · ${(data.jobs.items || []).filter((j) => ['Discovered','Reviewing','Saved'].includes(j.status)).length} need review</div><div class="filters">${filters.map(([id, label]) => `<button class="filter-btn ${id === activeFilter ? 'active' : ''}" data-filter="${id}">${label}</button>`).join('')}<span style="flex:1"></span><button class="subtab ${activeView === 'table' ? 'active' : ''}" data-job-view="table">Dense</button><button class="subtab ${activeView === 'board' ? 'active' : ''}" data-job-view="board">Board</button><button class="subtab ${activeView === 'cards' ? 'active' : ''}" data-job-view="cards">Cards</button></div>${body}<div class="note">Excluded rows stay visible and dimmed rather than disappearing, so a filter cutting too much is obvious.</div>`;
      for (const btn of document.querySelectorAll('[data-job-view]')) btn.addEventListener('click', () => renderJobs(data, btn.dataset.jobView, activeFilter));
      for (const btn of document.querySelectorAll('.filter-btn')) btn.addEventListener('click', () => renderJobs(data, activeView, btn.dataset.filter));
    }

    function passesFilter(job, filterId) {
      if (filterId === 'all') return job.status !== 'Archived';
      if (filterId === 'needs') return !job.scores?.career_ops || job.status === 'Discovered';
      if (filterId === 'score75') return (job.scores?.personal || 0) >= 75;
      if (filterId === 'stl') return !!job.location?.is_st_louis_metro;
      if (filterId === 'remote') return job.location?.work_mode === 'remote';
      if (filterId === 'closed') return ['Rejected', 'Withdrawn', 'Archived'].includes(job.status);
      return true;
    }

    function renderPipeline(data) {
      const stageOrder = data.pipeline.stage_order || [];
      const columns = data.pipeline.columns || {};
      document.getElementById('pipeline').innerHTML = `<div class="h1">Pipeline</div><div class="sub">${fmtMaybe(data.applications.total, 0)} in flight · compact board preview</div><div class="board">${stageOrder.map((stage) => { const items = (columns[stage] || []).slice(0, 4); return `<div class="column"><div class="colh"><span class="column-title">${escapeHtml(stage)}</span><span class="ct">${(columns[stage] || []).length}</span></div><div class="column-list">${items.length ? items.map((item) => `<div class="kc ${Number(item.personal_score || 0) >= 80 ? 'hi' : Number(item.personal_score || 0) < 70 ? 'risk' : ''}"><div class="r"><a href="/jobs/${escapeHtml(item.id)}" data-job-link="${escapeHtml(item.id)}">${escapeHtml(item.title)}</a></div><div class="c">${escapeHtml(item.company)}</div><div class="f"><span class="b stage">${escapeHtml(item.liveness_status || 'Unknown')}</span><span class="age">${fmtMaybe(item.personal_score, '—')}</span></div></div>`).join('') : '<div class="colempty">Nothing here yet.</div>'}</div></div>`; }).join('')}</div>`;
    }

    function renderMetrics(data) {
      const analytics = data.analytics || {};
      const byStatus = analytics.by_status || {};
      const funnel = analytics.funnel || {};
      const followup = analytics.followup_compliance || {};
      const resumeRows = analytics.resume_attribution || [];
      const warnings = analytics.warnings || [];
      document.getElementById('analytics').innerHTML = `
        <div class="page-hero"><div class="hero-stack"><div><div class="h1">Analytics</div><div class="sub">Funnel conversion, resume-version attribution, and follow-up compliance for the active search window.</div></div><div class="hero-flags"><span class="b stage">${escapeHtml(analytics.window || '90d')}</span>${funnel.small_sample ? '<span class="b sp-mid">small sample</span>' : '<span class="b sp-yes">stable sample</span>'}</div></div></div>
        <div class="hero-subgrid">
          <section class="summary-card"><h3>Funnel</h3><div class="summary-grid"><div class="summary-metric"><span class="label">Applied</span><span class="value">${fmtMaybe(funnel.applied, 0)}</span><span class="meta">sent</span></div><div class="summary-metric"><span class="label">Responded</span><span class="value">${fmtMaybe(funnel.responded, 0)}</span><span class="meta">${fmtMaybe(funnel.response_rate, 0)}%</span></div><div class="summary-metric"><span class="label">Interview</span><span class="value">${fmtMaybe(funnel.interview, 0)}</span><span class="meta">${fmtMaybe(funnel.interview_rate, 0)}%</span></div><div class="summary-metric"><span class="label">Offer</span><span class="value">${fmtMaybe(funnel.offer, 0)}</span><span class="meta">${fmtMaybe(funnel.offer_rate, 0)}%</span></div></div></section>
          <section class="summary-card"><h3>Follow-up compliance</h3><div class="summary-grid"><div class="summary-metric"><span class="label">Tracked</span><span class="value">${fmtMaybe(followup.tracked, 0)}</span><span class="meta">with due dates</span></div><div class="summary-metric"><span class="label">Completed</span><span class="value">${fmtMaybe(followup.completed, 0)}</span><span class="meta">${fmtMaybe(followup.completion_rate, 0)}%</span></div><div class="summary-metric"><span class="label">Due open</span><span class="value">${fmtMaybe(followup.due_open, 0)}</span><span class="meta">needs action</span></div><div class="summary-metric"><span class="label">Jobs</span><span class="value">${fmtMaybe(analytics.jobs_total, 0)}</span><span class="meta">tracked</span></div></div></section>
        </div>
        <div class="split" style="margin-top:24px">
          <div class="panel">
            <div class="kicker">08 · status mix</div>
            <div class="list" style="margin-top:16px;">${Object.entries(byStatus).map(([k,v]) => `<div class="job-card"><strong>${escapeHtml(k)}</strong><div class="muted">${v} jobs</div></div>`).join('') || '<div class="empty">No status metrics yet.</div>'}</div>
            ${warnings.length ? `<div class="note" style="margin-top:14px">${warnings.map(escapeHtml).join('<br>')}</div>` : ''}
          </div>
          <div class="panel">
            <div class="kicker">09 · resume attribution</div>
            <div class="list">${resumeRows.length ? resumeRows.map((row) => `<div class="job-card"><div class="variant-card-top"><div><strong>${escapeHtml(row.version_label || 'no resume variant')}</strong><div class="muted mono">${escapeHtml(row.resume_variant_id || 'unlinked')}</div></div><div class="score"><span>${fmtMaybe(row.response_rate, 0)}%</span></div></div><div class="job-flags"><span class="chip">${fmtMaybe(row.applications, 0)} apps</span><span class="chip">${fmtMaybe(row.responses, 0)} responses</span><span class="chip">${fmtMaybe(row.interviews, 0)} interviews</span></div></div>`).join('') : '<div class="empty">No application/resume attribution yet.</div>'}</div>
          </div>
        </div>
        <div class="panel" style="margin-top:24px"><div class="kicker">10 · top scoring roles</div><div class="list">${(analytics.top_jobs || []).map((job) => `<div class="job-card"><strong><a href="/jobs/${escapeHtml(job.id)}" data-job-link="${escapeHtml(job.id)}">${escapeHtml(job.title)}</a></strong><div class="muted">${escapeHtml(job.company)}</div><div class="job-meta"><span class="chip">Score ${fmtMaybe(job.personal_score)}</span><span class="chip">${escapeHtml(job.status)}</span></div></div>`).join('') || '<div class="empty">No top jobs available.</div>'}</div></div>`;
    }

    function renderAutomation(data) {
      const runs = data.runs.items || [];
      const failures = data.failures.items || [];
      document.getElementById('automation').innerHTML = `
        <div class=\"split\">
          <div class=\"panel\">
            <div class=\"kicker\">10 · automation health</div>
            <div class=\"metrics\">
              <div class=\"metric\"><div class=\"muted\">Health</div><div class=\"value\">${escapeHtml(data.status.health || 'unknown')}</div></div>
              <div class=\"metric\"><div class=\"muted\">Recent runs</div><div class=\"value\">${runs.length}</div></div>
              <div class=\"metric\"><div class=\"muted\">Failures</div><div class=\"value\">${failures.length}</div></div>
              <div class=\"metric\"><div class=\"muted\">Latest scan</div><div class=\"value\">${escapeHtml(data.status.latest_scan?.status || '—')}</div></div>
            </div>
            <div class=\"list\" style=\"margin-top:16px;\">${runs.slice(0, 8).map((run) => `<div class=\"job-card\"><header><div><strong>${escapeHtml(run.name)}</strong><div class=\"muted\">${escapeHtml(run.kind)} · ${fmtTime(run.started_at)}</div></div><span class=\"pill ${run.status === 'completed' ? 'good' : 'warn'}\">${escapeHtml(run.status)}</span></header><div class=\"muted\">exit ${fmtMaybe(run.exit_code)} · ${fmtMaybe(run.duration_ms)} ms</div></div>`).join('') || '<div class=\"empty\">No automation runs recorded yet.</div>'}</div>
          </div>
          <div class=\"panel\">
            <div class=\"kicker\">11 · failures + notes</div>
            ${failures.length ? `<div class=\"list\">${failures.map((f) => `<div class=\"job-card\"><strong>${escapeHtml(f.stage || 'failure')}</strong><div class=\"muted\">${fmtTime(f.created_at)}</div><div class=\"code\">${escapeHtml(f.error || '')}</div></div>`).join('')}</div>` : '<div class=\"empty\">No unresolved ingest failures. The remaining known caveat is unattended evaluate-cron reliability, not app persistence.</div>'}
          </div>
        </div>`;
    }

    function renderResumeStudio(data) {
      const prepJobs = (data.jobs.items || []).slice(0, 6);
      const match = INITIAL_PATH.match(/^[/]resume[/]([a-f0-9]+)$/);
      const workspace = data.resumeWorkspace || null;
      if (match && workspace && workspace.job) {
        const variant = (workspace.variants || [])[0] || null;
        const latestAnalysis = latestAtsAnalysis(variant);
        const present = workspace.analysis?.present_keywords || [];
        const safe = workspace.analysis?.safe_to_add || [];
        const blocked = workspace.analysis?.cannot_add || [];
        const currentScore = latestAnalysis?.score ?? workspace.analysis?.score ?? 0;
        const baselineScore = workspace.analysis?.score ?? 0;
        const suggestions = variant?.suggestions || [];
        const safeSuggestions = suggestions.filter((s) => s.is_safe);
        const blockedSuggestions = suggestions.filter((s) => !s.is_safe);
        const events = workspace.events || [];
        const sourceText = variant?.source_text || variant?.content_text || workspace.bases?.[0]?.content_text || '';
        const sourcePreview = sourceText.slice(0, 6000);
        const baseDoc = workspace.bases?.[0] || null;
        const coverageTotal = present.length + safe.length + blocked.length;
        const scoreDelta = Math.round(Number(currentScore || 0) - Number(baselineScore || 0));
        const variantCards = (workspace.variants || []).map((item) => {
          const ats = latestAtsAnalysis(item);
          return `<div class="job-card"><div class="variant-card-top"><div><strong>${escapeHtml(item.label || 'Resume variant')}</strong><div class="muted mono">${escapeHtml(item.version_label || '')} · rev ${fmtMaybe(item.revision, 1)} · ${escapeHtml(item.compile_status || 'draft')}</div></div>${scoreWidget(ats?.score ?? baselineScore)}</div><div class="job-flags"><span class="chip">${item.is_locked ? 'Immutable' : 'Editable'}</span><span class="chip">${fmtDateShort(item.updated_at)}</span></div><div class="hero-actions"><button class="btn" data-accept-safe="${escapeHtml(item.id)}">Accept safe</button><button class="btn" data-compile-variant="${escapeHtml(item.id)}">Compile</button><button class="btn" data-hm-audit="${escapeHtml(item.id)}">HM audit</button>${item.document ? `<a class="btn primary" href="/api/v1/resume/variants/${escapeHtml(item.id)}/download">Download PDF</a>` : ''}</div></div>`;
        }).join('');
        const sourcePanel = `<div class="code-pane">${nl2br(sourcePreview || 'No source text available.')}</div>`;
        const diffPanel = safeSuggestions.length ? `<div class="diff-list">${safeSuggestions.map((s) => `<div class="diff-card"><div class="eyebrow muted mono">${escapeHtml(s.term || s.kind || 'Suggestion')}</div><div class="before">${escapeHtml(s.original_text || 'Current wording not captured')}</div><div class="after">${escapeHtml(s.suggestion_text || '')}</div><div class="meta-line"><span>${escapeHtml(s.rationale || 'Verified suggestion')}</span></div></div>`).join('')}</div>` : '<div class="empty">No line-level safe diffs are available yet.</div>';
        const suggestionsPanel = safeSuggestions.length ? safeSuggestions.map((s) => `<div class="sugg"><div class="kd"><span>${escapeHtml(s.term || s.kind || 'Suggestion')}</span><span style="color:var(--positive)">safe</span></div>${s.original_text ? `<div class="bef">${escapeHtml(s.original_text)}</div>` : ''}<div class="aft">${escapeHtml(s.suggestion_text || '')}</div><div class="ev2">${escapeHtml(s.rationale || 'Verified suggestion')}</div><div class="acts2"><button class="btn primary" data-accept-one="${escapeHtml(s.id)}" data-variant-id="${escapeHtml(variant?.id || '')}">Accept</button></div></div>`).join('') : '<div class="empty">No safe suggestions generated yet.</div>';
        const guardrailsPanel = blockedSuggestions.length ? blockedSuggestions.map((s) => `<div class="sugg"><div class="kd"><span>${escapeHtml(s.term || s.kind || 'Guardrail')}</span><span style="color:var(--sev-critical)">blocked</span></div><div class="aft">${escapeHtml(s.suggestion_text || '')}</div><div class="ev2">${escapeHtml(s.rationale || 'Unsupported by verified resume evidence.')}</div><div class="note">This stays informational only and cannot be accepted automatically.</div></div>`).join('') : '<div class="empty">No fabrication-guarded terms for this workspace.</div>';
        document.getElementById('resume').innerHTML = `
          <div class="page-hero">
            <div class="hero-stack">
              <div><div class="h1">Resume Studio</div><div class="sub">${escapeHtml(workspace.job.title)} · ${escapeHtml(workspace.job.company?.name || 'Unknown company')} · base <span class="mono">${escapeHtml(baseDoc?.label || 'default')}</span> · variant <span class="mono">${escapeHtml(variant?.version_label || variant?.label || 'draft')}</span></div></div>
              <div class="hero-flags">${workModeBadge(workspace.job)}${sponsorshipBadge(workspace.job)}<span class="b stage">${escapeHtml(workspace.job.status || '—')}</span>${scorePill(workspace.job)}</div>
            </div>
            <div class="hero-actions"><button class="btn" id="tailor-now">Regenerate</button><button class="btn" data-hm-audit="${escapeHtml(variant?.id || '')}">HM audit</button><button class="btn" data-compile-variant="${escapeHtml(variant?.id || '')}">Compile</button>${variant ? `<a class="btn primary" href="/api/v1/resume/variants/${escapeHtml(variant.id)}/download">Download PDF</a>` : ''}</div>
          </div>
          <div class="hero-subgrid">
            <section class="summary-card"><h3>Target role summary</h3><div class="summary-grid"><div class="summary-metric"><span class="label">Baseline ATS</span><span class="value">${Math.round(Number(baselineScore || 0))}</span><span class="meta">initial fit</span></div><div class="summary-metric"><span class="label">Current ATS</span><span class="value">${Math.round(Number(currentScore || 0))}</span><span class="meta">latest analysis</span></div><div class="summary-metric"><span class="label">Coverage</span><span class="value">${present.length}/${coverageTotal || present.length || 1}</span><span class="meta">present keywords</span></div><div class="summary-metric"><span class="label">Compile</span><span class="value">${escapeHtml(variant?.compile_status || 'draft')}</span><span class="meta">${fmtDateShort(variant?.compiled_at || variant?.updated_at)}</span></div></div></section>
            <section class="summary-card"><h3>Operator notes</h3><ul class="why"><li><b>+${Math.max(0, scoreDelta)}</b>${escapeHtml(scoreDelta >= 0 ? 'Current variant preserves or improves baseline fit.' : 'Current variant trails the baseline; review suggested edits.')}</li><li><b>${safeSuggestions.length}</b>${escapeHtml(safeSuggestions.length ? 'Verified safe suggestions are ready for one-click acceptance.' : 'No extra safe suggestions remain.')}</li><li><b>${blockedSuggestions.length}</b>${escapeHtml(blockedSuggestions.length ? 'Fabrication guard blocked unsupported terms; review the guardrails tab before manual edits.' : 'No blocked claims in this workspace.')}</li></ul></section>
          </div>
          <div class="studio">
            <div class="stack">
              <section class="panel"><div class="ph"><h2>Requirements</h2><span class="mono">${present.length + safe.length}/${coverageTotal || (present.length + safe.length)}</span></div><div class="pb"><ul class="reqlist">${present.map((k) => `<li><span class="ok">✓</span>${escapeHtml(k)}</li>`).join('')}${safe.map((k) => `<li><span class="par">~</span>${escapeHtml(k)}</li>`).join('')}${blocked.map((k) => `<li><span class="no">✗</span>${escapeHtml(k)}</li>`).join('') || '<li><span class="ok">✓</span>No blocked requirements currently active.</li>'}</ul></div></section>
              <section class="panel"><div class="ph"><h2>Base document</h2></div><div class="pb timeline"><div class="r"><span class="dt">Base</span><span class="mono">${escapeHtml(baseDoc?.label || 'resume base')}</span><span class="who">${baseDoc?.source_path ? 'file' : 'stored text'}</span></div><div class="r"><span class="dt">Variant</span><span class="mono">${escapeHtml(variant?.label || 'draft')}</span><span class="who">${escapeHtml(variant?.compile_status || 'draft')}</span></div><div class="r"><span class="dt">Revision</span><span class="mono">rev ${fmtMaybe(variant?.revision, 1)}</span><span class="who">${variant?.is_locked ? 'immutable' : 'editable'}</span></div><div class="r"><span class="dt">Updated</span><span class="mono">${fmtDateShort(variant?.updated_at)}</span><span class="who">latest</span></div></div></section>
            </div>
            <section class="panel"><div class="tabs"><button class="tab active" data-resume-tab="preview">Preview</button><button class="tab" data-resume-tab="source">Source</button><button class="tab" data-resume-tab="diff">Diff <span class="mono" style="color:var(--accent)">${safeSuggestions.length}</span></button><button class="tab" data-resume-tab="suggestions">Suggestions <span class="mono" style="color:var(--accent)">${safeSuggestions.length}</span></button><button class="tab" data-resume-tab="guardrails">Guardrails <span class="mono" style="color:var(--sev-critical)">${blockedSuggestions.length}</span></button></div><div class="pb"><div class="tab-panel" data-resume-panel="preview"><div class="paper-wrap"><div class="paper"><h4>Sai Teja Kavuri</h4><div class="cl">Resume variant preview · recruiter-safe content</div><div class="paper-body">${paragraphize(sourcePreview || 'No preview available.')}</div></div></div><div class="pagemark"><span>Page 1 of 1</span><span class="ln"></span><span>${variant?.compile_status === 'compiled' ? 'compiled' : 'draft'}</span></div></div><div class="tab-panel" data-resume-panel="source" hidden>${sourcePanel}</div><div class="tab-panel" data-resume-panel="diff" hidden>${diffPanel}</div><div class="tab-panel" data-resume-panel="suggestions" hidden>${suggestionsPanel}<div class="note">Blocked suggestions stay out of the normal action surface; only verified safe edits appear here.</div></div><div class="tab-panel" data-resume-panel="guardrails" hidden>${guardrailsPanel}</div></div></section>
            <div class="stack">
              <section class="panel"><div class="ph"><h2>ATS fitness</h2><span class="mono">from latest analysis</span></div><div class="pb"><div class="delta"><span class="old">${Math.round(Number(baselineScore || 0))}</span><span class="arrow">→</span><span class="newv">${Math.round(Number(currentScore || 0))}</span><span class="plus">${scoreDelta >= 0 ? '+' : ''}${scoreDelta}</span></div><div class="megabar" style="margin-top:12px"><i style="width:${Math.max(2, Math.min(100, Number(currentScore || 0)))}%"></i></div><div class="fit" style="margin-top:10px"><div class="fitrow"><span class="lbl">Present keywords</span><span class="val">${present.length}</span></div><div class="fitrow"><span class="lbl">Safe to add</span><span class="val">${safe.length}</span></div><div class="fitrow"><span class="lbl">Blocked claims</span><span class="val bad">${blocked.length}</span></div><div class="fitrow"><span class="lbl">Coverage</span><span class="val">${workspace.analysis?.keyword_coverage ? Math.round(Number(workspace.analysis.keyword_coverage)) + '%' : '—'}</span></div><div class="fitrow"><span class="lbl">Last phase</span><span class="val">${escapeHtml(latestAnalysis?.phase || workspace.analysis?.phase || 'baseline')}</span></div></div></div></section>
              <section class="panel"><div class="ph"><h2>Keywords</h2></div><div class="pb"><div class="kwgroup" style="margin-top:0"><div class="kwtitle"><span>Present</span><span>${present.length}</span></div>${present.length ? `<div class="kw present"><span class="mk">✓</span><div>${escapeHtml(present.join(' · '))}<span class="bk">Extracted from the current variant</span></div></div>` : '<div class="empty">No present keywords yet.</div>'}</div><div class="kwgroup"><div class="kwtitle"><span>Safe to add</span><span>${safe.length}</span></div>${safe.map((k) => `<div class="kw safe"><span class="mk">☐</span><div>${escapeHtml(k)}<span class="bk">Backed by verified resume facts</span></div></div>`).join('') || '<div class="empty">No additional safe keywords right now.</div>'}</div><div class="kwgroup"><div class="kwtitle"><span>Cannot add</span><span>${blocked.length}</span></div>${blocked.map((k) => `<div class="kw block"><span class="mk">⚠</span><div>${escapeHtml(k)}<span class="bk">Unsupported by current evidence. Hold for operator review only.</span></div></div>`).join('') || '<div class="empty">No blocked keywords.</div>'}</div></div></section>
            </div>
          </div>
          <div class="sechead"><h2>Stored variants</h2><div class="rule"></div><span class="meta">${fmtMaybe(workspace.variants?.length, 0)}</span></div><div class="variant-grid">${variantCards || '<div class="empty">No tailored variants stored yet for this job.</div>'}</div>
          <div class="sechead"><h2>Resume event feed</h2><div class="rule"></div><span class="meta">live · latest first</span></div><div class="event-feed" id="resume-events">${events.length ? events.map(renderEventCard).join('') : '<div class="empty">No resume events yet.</div>'}</div>`;
        const tailorNow = document.getElementById('tailor-now');
        if (tailorNow) tailorNow.addEventListener('click', async () => {
          const original = tailorNow.textContent;
          tailorNow.disabled = true;
          tailorNow.textContent = 'Tailoring…';
          try {
            const base = workspace.bases?.[0];
            await postJson('/api/v1/resume/tailor', { job_id: workspace.job.id, base_id: base?.id || null, label: `${workspace.job.title} tailored resume` });
            location.reload();
          } catch (error) {
            tailorNow.disabled = false;
            tailorNow.textContent = original || 'Regenerate';
            renderInlineError('resume', 'Tailoring failed — try again', error);
          }
        });
        for (const btn of document.querySelectorAll('[data-accept-safe]')) btn.addEventListener('click', async () => { if (!btn.dataset.acceptSafe) return; await fetch(`/api/v1/resume/variants/${btn.dataset.acceptSafe}/accept-safe`, { method: 'POST', credentials: 'same-origin' }); location.reload(); });
        for (const btn of document.querySelectorAll('[data-accept-one]')) btn.addEventListener('click', async () => { await fetch(`/api/v1/resume/variants/${btn.dataset.variantId}/suggestions/${btn.dataset.acceptOne}`, { method: 'POST', credentials: 'same-origin' }); location.reload(); });
        for (const btn of document.querySelectorAll('[data-compile-variant]')) btn.addEventListener('click', async () => { if (!btn.dataset.compileVariant) return; await fetch(`/api/v1/resume/variants/${btn.dataset.compileVariant}/compile`, { method: 'POST', credentials: 'same-origin' }); location.reload(); });
        for (const btn of document.querySelectorAll('[data-hm-audit]')) btn.addEventListener('click', async () => { if (!btn.dataset.hmAudit) return; await fetch(`/api/v1/resume/variants/${btn.dataset.hmAudit}/hm-audit`, { method: 'POST', credentials: 'same-origin' }); location.reload(); });
        for (const tab of document.querySelectorAll('[data-resume-tab]')) {
          tab.addEventListener('click', () => {
            const id = tab.dataset.resumeTab;
            document.querySelectorAll('[data-resume-tab]').forEach((el) => el.classList.toggle('active', el === tab));
            document.querySelectorAll('[data-resume-panel]').forEach((panel) => { panel.hidden = panel.dataset.resumePanel !== id; });
          });
        }
        const evtSource = new EventSource(`/api/v1/events?stream=resume&job_id=${encodeURIComponent(workspace.job.id)}`);
        evtSource.addEventListener('resume_snapshot', (event) => { try { const body = JSON.parse(event.data); const items = body.payload?.items || []; const container = document.getElementById('resume-events'); if (container) container.innerHTML = items.length ? items.map(renderEventCard).join('') : '<div class="empty">No resume events yet.</div>'; } catch (err) { console.warn('resume event parse failed', err); } });
        return;
      }
      document.getElementById('resume').innerHTML = `<div class="h1">Resume Studio</div><div class="sub">Register a base resume once, then open a job-specific workspace to analyze fit and generate a targeted variant.</div><div class="reco" style="margin-top:16px">${prepJobs.map((job) => `<article class="card"><div class="top"><div><h3><a href="/resume/${escapeHtml(job.id)}">${escapeHtml(job.title)}</a></h3><div class="co">${escapeHtml(job.company?.name || '—')}</div></div>${scoreWidget(job.scores?.personal)}</div><div class="row">${workModeBadge(job)}${sponsorshipBadge(job)}</div>${renderActionButtons(job)}</article>`).join('') || '<div class="empty">No jobs available for preparation yet.</div>'}</div>`;
    }

    function renderApplications(data) {
      const rows = data.applications.items || [];
      document.getElementById('applications').innerHTML = `<div class=\"panel\"><div class=\"kicker\">10 · applications</div><div style=\"overflow:auto\"><table><thead><tr><th>Company</th><th>Role</th><th>Applied</th><th>Stage</th><th>Resume</th><th>Next action</th></tr></thead><tbody>${rows.length ? rows.map((app) => `<tr><td>${escapeHtml(app.company?.name || '—')}</td><td><a href=\"/jobs/${escapeHtml(app.job?.id || '')}\" data-job-link=\"${escapeHtml(app.job?.id || '')}\">${escapeHtml(app.job?.title || '—')}</a></td><td>${fmtTime(app.applied_at)}</td><td>${escapeHtml(app.stage || '—')}</td><td>${escapeHtml(app.resume?.version_label || app.resume?.title || '—')}</td><td>${escapeHtml(app.next_action || '—')}</td></tr>`).join('') : '<tr><td colspan="6" class="muted">No applications recorded yet.</td></tr>'}</tbody></table></div></div>`;
    }

    function renderCompanies(data) {
      const rows = data.companies.items || [];
      const body = data.companies.status === 'loading' ? loadingRows(4, 'Loading companies…') : (rows.length ? rows.map((company) => `<tr><td>${escapeHtml(company.name || '—')}</td><td>${escapeHtml(company.domain || '—')}</td><td>${fmtMaybe(company.priority, '—')}</td><td>${company.is_target ? 'Yes' : 'No'}</td></tr>`).join('') : '<tr><td colspan="4" class="muted">No companies tracked yet.</td></tr>');
      document.getElementById('companies').innerHTML = `<div class=\"panel\"><div class=\"kicker\">11 · companies</div><div style=\"overflow:auto\"><table><thead><tr><th>Name</th><th>Domain</th><th>Priority</th><th>Target</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
    }

    function renderContacts(data) {
      const rows = data.contacts.items || [];
      const body = data.contacts.status === 'loading' ? loadingRows(4, 'Loading contacts…') : (rows.length ? rows.map((contact) => `<tr><td>${escapeHtml(contact.full_name || '—')}</td><td>${escapeHtml(contact.company_name || '—')}</td><td>${escapeHtml(contact.title || '—')}</td><td>${escapeHtml(contact.email || '—')}</td></tr>`).join('') : '<tr><td colspan="4" class="muted">No contacts stored yet.</td></tr>');
      document.getElementById('contacts').innerHTML = `<div class=\"panel\"><div class=\"kicker\">12 · contacts</div><div style=\"overflow:auto\"><table><thead><tr><th>Name</th><th>Company</th><th>Title</th><th>Email</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
    }

    function renderDocuments(data) {
      const rows = data.documents.items || [];
      document.getElementById('documents').innerHTML = `<div class=\"panel\"><div class=\"kicker\">13 · documents</div><div style=\"overflow:auto\"><table><thead><tr><th>Kind</th><th>Title</th><th>Version</th><th>Path / content</th></tr></thead><tbody>${rows.length ? rows.map((doc) => `<tr><td>${escapeHtml(doc.kind || '—')}</td><td>${escapeHtml(doc.title || '—')}</td><td>${escapeHtml(doc.version_label || '—')}</td><td>${escapeHtml(doc.file_path || doc.content_text || 'stored')}</td></tr>`).join('') : '<tr><td colspan="4" class="muted">No documents stored yet.</td></tr>'}</tbody></table></div></div>`;
    }

    function renderInterviews(data) {
      const rows = data.interviews.items || [];
      document.getElementById('interviews').innerHTML = `<div class=\"panel\"><div class=\"kicker\">14 · interviews</div><div class=\"timeline\">${rows.length ? rows.map((item) => `<div class=\"timeline-item\"><strong>${escapeHtml(item.interview_type || 'Interview')}</strong><div class=\"muted\">${fmtTime(item.scheduled_at)} · ${escapeHtml(item.stage || 'scheduled')}</div><div>${escapeHtml(item.notes || item.location || 'No notes')}</div></div>`).join('') : '<div class=\"empty\">No interviews scheduled yet.</div>'}</div></div>`;
    }

    function renderSettings() {
      document.getElementById('settings').innerHTML = `<div class=\"panel\"><div class=\"kicker\">15 · settings</div><h2>Profile, targets, exclusions, sources, sponsorship, automation, and security live here in the original specification.</h2><p class=\"muted\">The backend settings APIs are not fully expanded yet, but the product IA is now in place so the dashboard no longer hides the intended system shape.</p></div>`;
    }

    function renderDetail(job) {
      const snapshotText = job?.snapshots?.[0]?.content_text || job?.description_text || '';
      const activity = (job?.events || []).slice(0, 8);
      const sources = job?.sources || [];
      const sponsorEvidence = (job?.sponsorship_evidence || []).slice(0, 3);
      document.getElementById('detail').innerHTML = !job ? `<div class="panel"><div class="empty">Select a job from Today, Board, or Table to inspect its stored evidence, scoring, and event history.</div></div>` : `
        <div class="page-hero">
          <div class="hero-stack">
            <div><div class="h1">${escapeHtml(job.title)}</div><div class="sub"><span class="mono">${escapeHtml(job.company?.name || 'Unknown company')}</span> · ${escapeHtml(job.location?.raw || 'Unknown')} · ${escapeHtml(job.salary_text || 'Salary not stored')} · posted ${agoLabel(job.sources?.[0]?.discovered_at || job.created_at)}</div></div>
            <div class="hero-flags">${workModeBadge(job)}${sponsorshipBadge(job)}<span class="b new">${escapeHtml(job.liveness_status || 'Unknown')}</span><span class="b stage">${escapeHtml(job.status || '—')}</span>${scorePill(job)}</div>
          </div>
          <div class="hero-actions"><div class="acts"><a class="btn primary" href="/resume/${escapeHtml(job.id)}">Tailor resume</a>${job.application_url ? `<a class="btn" href="${escapeHtml(job.application_url)}" target="_blank" rel="noreferrer">Open original job ↗</a>` : ''}<button class="btn" type="button">Save</button><button class="btn" type="button">Skip</button></div></div>
        </div>
        <div class="hero-subgrid">
          <section class="summary-card"><h3>Decision summary</h3><div class="summary-grid"><div class="summary-metric"><span class="label">Personal match</span><span class="value">${fmtMaybe(job.scores?.personal, 0)}</span><span class="meta">score v${fmtMaybe(job.scores?.version, '—')}</span></div><div class="summary-metric"><span class="label">Career-ops</span><span class="value">${escapeHtml(careerOpsState(job).value)}</span><span class="meta">${escapeHtml(careerOpsState(job).label)}</span></div><div class="summary-metric"><span class="label">Tier</span><span class="value">${escapeHtml(job.scores?.tier || '—')}</span><span class="meta">priority class</span></div><div class="summary-metric"><span class="label">Sources</span><span class="value">${fmtMaybe(sources.length, 0)}</span><span class="meta">tracked copies</span></div></div></section>
          <section class="summary-card"><h3>Why this role is surfaced</h3><ul class="why">${topReasons(job).map((reason, i) => `<li><b>+${Math.max(4, 16 - i*3)}</b>${escapeHtml(reason)}</li>`).join('') || '<li><b>+0</b>No top reasons stored.</li>'}</ul></section>
        </div>
        <div class="detail" style="margin-top:24px">
          <div class="stack">
            <section class="panel"><div class="ph"><h2>Match analysis</h2><span class="mono" style="font-size:10px;color:var(--text-tertiary)">score_version ${escapeHtml(job.scores?.version || '—')}</span></div><div class="pb receipt"><div class="hdr"><span>Personal match</span><span class="total-n">${fmtMaybe(job.scores?.personal, 0)}<span style="font-size:13px;color:var(--text-tertiary)"> / 100</span></span></div><div class="megabar"><i style="width:${Math.max(2, Math.min(100, Number(job.scores?.personal || 0)))}%"></i></div>${renderBreakdownRows(job)}<div class="rdiv"></div><div class="rtot"><span>${fmtMaybe(job.scores?.personal, 0)}</span><span>TOTAL</span><span style="color:var(--text-tertiary);font-weight:400">clamped 0–100</span></div>${job.application?.careerops_tracker_num || job.scores?.career_ops ? `<div class="careerops-line"><div><div class="muted mono">Career-Ops evaluation</div><div class="muted2" style="margin-top:4px">${escapeHtml(careerOpsState(job).help)} · ${job.application?.careerops_state ? escapeHtml(job.application.careerops_state) : escapeHtml(careerOpsState(job).label)}</div></div><div><span class="value">${escapeHtml(careerOpsState(job).value)}</span><span style="color:var(--text-tertiary);font-size:12px">${job.scores?.career_ops ? ' / 5' : ''}</span></div></div>` : ''}</div></section>
            <section class="panel"><div class="ph"><h2>Concerns and gaps</h2></div><div class="pb"><ul class="concerns-list">${concernText(job).length ? concernText(job).map((c) => `<li><span style="color:var(--sev-medium);font-family:var(--font-mono)">!</span><div>${escapeHtml(c)}</div></li>`).join('') : '<li><span style="color:var(--positive);font-family:var(--font-mono)">✓</span><div>No explicit concerns stored.</div></li>'}</ul></div></section>
            <section class="panel"><div class="ph"><h2>Job description</h2><span class="mono" style="font-size:10px;color:var(--text-tertiary)">${fmtMaybe(job.sources?.[0]?.source_platform, 'stored')}</span></div><div class="pb">${String(snapshotText || '').toLowerCase().includes('ai assistant') ? `<div class="injbanner"><div><b>⚑ Suspicious content — treated as data</b>This posting contains text that appears addressed to an automated reviewer. It is stored for audit and should not influence scoring.</div></div>` : ''}<div class="jdbox">${paragraphize(snapshotText || 'No description stored.')}</div></div></section>
          </div>
          <div class="stack">
            <section class="panel"><div class="ph"><h2>Sponsorship analysis</h2>${sponsorshipBadge(job)}</div><div class="pb">${sponsorEvidence.length ? sponsorEvidence.map((ev) => `<div class="evidence-card"><div class="eyebrow"><span>${escapeHtml(ev.signal_type || 'signal')}</span><span>${escapeHtml(sourceYearLabel(ev))} · Retrieved ${fmtDateShort(ev.created_at)}</span></div><div class="quote">${escapeHtml(ev.evidence_text || ev.quoted_span || ev.class_implied || 'No evidence text')}</div><div class="meta-line"><span>${escapeHtml(ev.class_implied || job.sponsorship?.class || '—')}</span><span>${escapeHtml(ev.source_url || 'stored evidence')}</span></div><div class="note" style="margin-top:8px">${escapeHtml(sponsorshipDerivation(job, ev))}</div></div>`).join('') : `<div class="evidence-card"><div class="eyebrow"><span>Summary</span><span>${escapeHtml(job.sponsorship?.class || 'unknown')}</span></div><div class="quote">${escapeHtml(job.sponsorship?.evidence_summary || 'No sponsorship evidence stored.')}</div></div>`}<div class="note">${escapeHtml(sponsorshipDerivation(job, sponsorEvidence[0] || null))}<br>Derived signals are advisory only; use them as prioritization context rather than a guarantee.</div></div></section>
            <section class="panel"><div class="ph"><h2>Activity</h2></div><div class="pb timeline">${activity.length ? activity.map((event) => `<div class="r"><span class="dt">${fmtDateShort(event.occurred_at)}</span><span>${escapeHtml(event.event_type)}</span><span class="who">${escapeHtml(event.actor || 'system')}</span></div>`).join('') : '<div class="colempty">No activity recorded yet.</div>'}</div></section>
            <section class="panel"><div class="ph"><h2>Sources</h2><span class="mono" style="font-size:10px;color:var(--text-tertiary)">seen on ${fmtMaybe(sources.length, 0)}</span></div><div class="pb timeline">${sources.length ? sources.map((src) => `<div class="r"><span class="dt">${escapeHtml(src.source_platform || 'source')}</span><span style="color:var(--text-secondary);font-size:10.5px;word-break:break-all">${escapeHtml(src.source_url || '—')}</span><span class="who">${fmtDateShort(src.discovered_at)}</span></div>`).join('') : '<div class="colempty">No sources stored.</div>'}</div></section>
          </div>
        </div>`;
    }

    async function refreshOptionalState(state) {
      const update = async (key, path, fallback, timeoutMs = 10000) => {
        state[key] = await fetchJsonOptional(path, fallback, timeoutMs);
      };
      await update('pipeline', '/api/v1/pipeline', state.pipeline, 10000);
      await update('analytics', '/api/v1/analytics?window=90d', state.analytics, 10000);
      await update('digest', '/api/v1/digest?since=24h', state.digest, 10000);
      await update('applications', '/api/v1/applications', state.applications, 10000);
      await update('companies', '/api/v1/companies', state.companies, 10000);
      await update('contacts', '/api/v1/contacts', state.contacts, 10000);
      await update('documents', '/api/v1/documents', state.documents, 10000);
      await update('interviews', '/api/v1/interviews', state.interviews, 10000);
      await update('resumeBases', '/api/v1/resume/bases', state.resumeBases, 10000);
      await update('queue', '/api/v1/jobs/evaluation-queue?limit=8', state.queue, 10000);
      await update('runs', '/api/v1/automation/runs?limit=10', state.runs, 10000);
      await update('failures', '/api/v1/automation/failures', state.failures, 10000);
      await update('health', '/api/v1/health', state.health, 6000);
      await update('status', '/api/v1/automation/status', state.status, 6000);
      const activeId = document.querySelector('.section.active')?.id || 'today';
      document.getElementById('scan-pill').innerHTML = scanPill(state);
      renderToday(state);
      renderJobs(state);
      renderPipeline(state);
      renderResumeStudio(state);
      renderApplications(state);
      renderInterviews(state);
      renderCompanies(state);
      renderContacts(state);
      renderDocuments(state);
      renderMetrics(state);
      renderAutomation(state);
      renderPrimaryNav(activeId, state);
      showSection(activeId);
      bindJobLinks(state);
    }

    async function boot() {
      try {
        const resumeMatch = INITIAL_PATH.match(/^[/]resume[/]([a-f0-9]+)$/);
        const jobs = await fetchJson('/api/v1/jobs', { timeoutMs: 10000 });
        let pipeline = { stage_order: [], columns: {} };
        let analytics = { window: '90d', by_status: {}, funnel: {}, followup_compliance: {}, resume_attribution: [], warnings: [], top_jobs: [], jobs_total: 0 };
        let digest = { new_jobs_count: 0, followups_due_count: 0, top_jobs: [], followups: [], latest_scan: null };
        let health = { status: 'loading', database: 'unknown', adapter: 'unknown', checks: {}, warnings: ['Health check is loading in the background.'] };
        let status = { health: 'loading', latest_scan: null, next_scan_at: null, warning: 'Automation status is loading in the background.' };
        let runs = { items: [], total: 0, status: 'loading' };
        let failures = { items: [], total: 0, status: 'loading' };
        let queue = { items: [], total: 0 };
        let applications = { items: [], total: 0 };
        let companies = { items: [], total: 0, status: 'loading' };
        let contacts = { items: [], total: 0, status: 'loading' };
        let documents = { items: [], total: 0, status: 'loading' };
        let interviews = { items: [], total: 0, status: 'loading' };
        let resumeBases = { items: [], total: 0, status: 'loading' };
        let resumeWorkspace = resumeMatch ? await fetchJsonOptional(`/api/v1/jobs/${resumeMatch[1]}/resume`, null, 5000) : null;
        const state = { jobs, pipeline, analytics, digest, health, status, runs, failures, queue, applications, companies, contacts, documents, interviews, resumeBases, resumeWorkspace };
        window.__JR_STATE = state;
        document.getElementById('scan-pill').innerHTML = scanPill(state);
        renderToday(state);
        renderJobs(state);
        renderPipeline(state);
        renderResumeStudio(state);
        renderApplications(state);
        renderInterviews(state);
        renderCompanies(state);
        renderContacts(state);
        renderDocuments(state);
        renderMetrics(state);
        renderAutomation(state);
        renderSettings();
        let initialSection = 'today';
        const sectionByPath = new Map(sections.map((s) => [s.path, s.id]));
        if (sectionByPath.has(INITIAL_PATH)) initialSection = sectionByPath.get(INITIAL_PATH);
        let detailJob = null;
        const match = INITIAL_PATH.match(/^[/]jobs[/]([a-f0-9]+)$/);
        if (match) {
          detailJob = await fetchJson(`/api/v1/jobs/${match[1]}`);
          initialSection = 'detail';
        }
        if (resumeMatch) {
          initialSection = 'resume';
        }
        renderDetail(detailJob);
        showSection(initialSection);
        renderPrimaryNav(initialSection, state);
        bindJobLinks(state);
        const searchInput = document.getElementById('global-search');
        searchInput.addEventListener('keydown', async (event) => {
          if (event.key !== 'Enter') return;
          const q = searchInput.value.trim();
          if (!q) return;
          const result = await fetchJson(`/api/v1/search?q=${encodeURIComponent(q)}`);
          document.getElementById('jobs').innerHTML = `<div class=\"panel\"><div class=\"kicker\">search</div><h2>Search results for ${escapeHtml(q)}</h2><div class=\"split\"><div><h3>Jobs</h3><div class=\"list\">${(result.jobs || []).map((job) => `<div class=\"job-card\"><strong><a href=\"/jobs/${escapeHtml(job.id)}\" data-job-link=\"${escapeHtml(job.id)}\">${escapeHtml(job.title)}</a></strong><div class=\"muted\">${escapeHtml(job.company?.name || '—')}</div></div>`).join('') || '<div class=\"empty\">No jobs found.</div>'}</div></div><div><h3>Companies</h3><div class=\"list\">${(result.companies || []).map((c) => `<div class=\"job-card\"><strong>${escapeHtml(c.name || '—')}</strong><div class=\"muted\">${escapeHtml(c.domain || '—')}</div></div>`).join('') || '<div class=\"empty\">No companies found.</div>'}</div></div></div></div>`;
          bindJobLinks(state);
          showSection('jobs');
          renderPrimaryNav('jobs', state);
        });
      } catch (error) {
        const failureTarget = document.querySelector('.main') || document.body;
        failureTarget.innerHTML = `<div class=\"panel\"><div class=\"pb\"><h2>Dashboard failed to load</h2><div class=\"code\">${escapeHtml(error?.message || error)}</div></div></div>`;
      }
    }

    boot();
  </script>
</body>
</html>
"""


def render_app_html(initial_path: str) -> str:
    return APP_HTML.replace("__INITIAL_PATH__", initial_path)


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Job Radar")

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        settings = get_settings()
        if (
            not settings.disable_login
            and settings.require_cloudflare_access
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and not request.headers.get("CF-Access-Jwt-Assertion")
            and not request.headers.get("CF-Access-Authenticated-User-Email")
        ):
            response = JSONResponse({"error": "cloudflare_access_required"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_: Request, exc: PermissionError):
        if str(exc) == "cloudflare_access_required":
            return JSONResponse({"error": "cloudflare_access_required"}, status_code=403)
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        if str(exc) == "csrf_required":
            return JSONResponse({"error": "csrf_required"}, status_code=403)
        return JSONResponse({"error": "validation_error"}, status_code=422)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz")
    async def readyz(settings: Settings = Depends(get_settings)) -> dict[str, object]:
        return get_readiness(settings)

    @app.get("/robots.txt", response_class=PlainTextResponse)
    async def robots_txt() -> str:
        return "User-agent: *\nDisallow: /\n"

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(error: str | None = None, settings: Settings = Depends(get_settings)) -> str:
        if settings.disable_login:
            return render_app_html("/")
        error_html = f'<div class="err">{error}</div>' if error else ''
        return LOGIN_HTML.format(error_html=error_html)

    @app.post("/auth/login")
    async def login(password: str = Form(...), settings: Settings = Depends(get_settings)):
        if settings.disable_login:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        store = SessionStore(settings)
        if not store.verify_password(password):
            return HTMLResponse(LOGIN_HTML.format(error_html='<div class="err">Invalid password</div>'), status_code=401)
        session = store.create_session()
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            settings.session_cookie,
            session.session_id,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            settings.csrf_cookie,
            session.csrf_token,
            httponly=False,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/auth/logout")
    async def logout(request: Request, settings: Settings = Depends(get_settings)):
        if settings.disable_login:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        session_id = request.cookies.get(settings.session_cookie)
        if session_id:
            SessionStore(settings).destroy_session(session_id)
        response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        response.delete_cookie(settings.session_cookie, path="/")
        response.delete_cookie(settings.csrf_cookie, path="/")
        return response

    def _ensure_browser_session(request: Request, settings: Settings) -> RedirectResponse | None:
        if settings.disable_login:
            return None
        session_id = request.cookies.get(settings.session_cookie)
        store = SessionStore(settings)
        if not session_id or not store.exists(session_id):
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request, settings: Settings = Depends(get_settings)):
        redirect = _ensure_browser_session(request, settings)
        if redirect:
            return redirect
        return render_app_html(request.url.path)

    @app.get("/jobs", response_class=HTMLResponse)
    async def jobs(request: Request, settings: Settings = Depends(get_settings)):
        redirect = _ensure_browser_session(request, settings)
        if redirect:
            return redirect
        return render_app_html(request.url.path)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail_page(job_id: str, request: Request, settings: Settings = Depends(get_settings)):
        redirect = _ensure_browser_session(request, settings)
        if redirect:
            return redirect
        return render_app_html(request.url.path)

    @app.get("/pipeline", response_class=HTMLResponse)
    @app.get("/resume", response_class=HTMLResponse)
    @app.get("/resume/{job_id}", response_class=HTMLResponse)
    @app.get("/applications", response_class=HTMLResponse)
    @app.get("/interviews", response_class=HTMLResponse)
    @app.get("/companies", response_class=HTMLResponse)
    @app.get("/contacts", response_class=HTMLResponse)
    @app.get("/documents", response_class=HTMLResponse)
    @app.get("/analytics", response_class=HTMLResponse)
    @app.get("/automation", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    async def shell_pages(request: Request, settings: Settings = Depends(get_settings)):
        redirect = _ensure_browser_session(request, settings)
        if redirect:
            return redirect
        return render_app_html(request.url.path)

    @app.get("/api/v1/jobs")
    async def api_jobs(_: str = Depends(require_session)):
        return list_jobs()

    @app.get("/api/v1/applications")
    async def api_applications(_: str = Depends(require_session)):
        return list_applications()

    @app.post("/api/v1/jobs/manual", status_code=201)
    async def api_jobs_manual(payload: dict, actor: str = Depends(require_write_session)):
        return import_manual_job(payload, actor=actor)

    @app.get("/api/v1/search")
    async def api_search(q: str = "", _: str = Depends(require_session)):
        return search_resources(q)

    @app.get("/api/v1/companies")
    async def api_companies(_: str = Depends(require_session)):
        return list_companies()

    @app.post("/api/v1/companies", status_code=201)
    async def api_create_company(payload: dict, _: str = Depends(require_write_session)):
        return create_company(payload)

    @app.get("/api/v1/companies/{company_id}")
    async def api_company(company_id: str, _: str = Depends(require_session)):
        try:
            return get_company(company_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "company_id": company_id}, status_code=404)

    @app.put("/api/v1/companies/{company_id}")
    async def api_update_company(company_id: str, payload: dict, _: str = Depends(require_write_session)):
        try:
            return update_company(company_id, payload)
        except KeyError:
            return JSONResponse({"error": "not_found", "company_id": company_id}, status_code=404)

    @app.delete("/api/v1/companies/{company_id}")
    async def api_delete_company(company_id: str, _: str = Depends(require_write_session)):
        try:
            return delete_company(company_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "company_id": company_id}, status_code=404)

    @app.get("/api/v1/documents")
    async def api_documents(_: str = Depends(require_session)):
        return list_documents()

    @app.post("/api/v1/documents", status_code=201)
    async def api_create_document(payload: dict, _: str = Depends(require_write_session)):
        return create_document(payload)

    @app.get("/api/v1/documents/{document_id}")
    async def api_document(document_id: str, _: str = Depends(require_session)):
        try:
            return get_document(document_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "document_id": document_id}, status_code=404)

    @app.put("/api/v1/documents/{document_id}")
    async def api_update_document(document_id: str, payload: dict, _: str = Depends(require_write_session)):
        try:
            return update_document(document_id, payload)
        except KeyError:
            return JSONResponse({"error": "not_found", "document_id": document_id}, status_code=404)

    @app.delete("/api/v1/documents/{document_id}")
    async def api_delete_document(document_id: str, _: str = Depends(require_write_session)):
        try:
            return delete_document(document_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "document_id": document_id}, status_code=404)

    @app.get("/api/v1/contacts")
    async def api_contacts(_: str = Depends(require_session)):
        return list_contacts()

    @app.post("/api/v1/contacts", status_code=201)
    async def api_create_contact(payload: dict, _: str = Depends(require_write_session)):
        return create_contact(payload)

    @app.get("/api/v1/contacts/{contact_id}")
    async def api_contact(contact_id: str, _: str = Depends(require_session)):
        try:
            return get_contact(contact_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "contact_id": contact_id}, status_code=404)

    @app.put("/api/v1/contacts/{contact_id}")
    async def api_update_contact(contact_id: str, payload: dict, _: str = Depends(require_write_session)):
        try:
            return update_contact(contact_id, payload)
        except KeyError:
            return JSONResponse({"error": "not_found", "contact_id": contact_id}, status_code=404)

    @app.delete("/api/v1/contacts/{contact_id}")
    async def api_delete_contact(contact_id: str, _: str = Depends(require_write_session)):
        try:
            return delete_contact(contact_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "contact_id": contact_id}, status_code=404)

    @app.get("/api/v1/interviews")
    async def api_interviews(_: str = Depends(require_session)):
        return list_interviews()

    @app.post("/api/v1/interviews", status_code=201)
    async def api_create_interview(payload: dict, _: str = Depends(require_write_session)):
        return create_interview(payload)

    @app.get("/api/v1/interviews/{interview_id}")
    async def api_interview(interview_id: str, _: str = Depends(require_session)):
        try:
            return get_interview(interview_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "interview_id": interview_id}, status_code=404)

    @app.put("/api/v1/interviews/{interview_id}")
    async def api_update_interview(interview_id: str, payload: dict, _: str = Depends(require_write_session)):
        try:
            return update_interview(interview_id, payload)
        except KeyError:
            return JSONResponse({"error": "not_found", "interview_id": interview_id}, status_code=404)

    @app.delete("/api/v1/interviews/{interview_id}")
    async def api_delete_interview(interview_id: str, _: str = Depends(require_write_session)):
        try:
            return delete_interview(interview_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "interview_id": interview_id}, status_code=404)

    @app.post("/api/v1/import/manual")
    async def api_import_manual(_: str = Depends(require_write_session)):
        return import_legacy_processed()

    @app.get("/api/v1/resume/bases")
    async def api_resume_bases(_: str = Depends(require_session)):
        return list_resume_bases()

    @app.post("/api/v1/resume/bases", status_code=201)
    async def api_create_resume_base(payload: dict, _: str = Depends(require_write_session)):
        return create_resume_base(payload)

    @app.post("/api/v1/resume/analyze")
    async def api_resume_analyze(payload: dict, _: str = Depends(require_write_session)):
        try:
            return analyze_resume_fit(str(payload.get("job_id") or ""), payload)
        except KeyError as exc:
            return JSONResponse({"error": "not_found", "detail": str(exc)}, status_code=404)

    @app.post("/api/v1/resume/tailor", status_code=201)
    async def api_resume_tailor(payload: dict, actor: str = Depends(require_write_session)):
        try:
            return tailor_resume_for_job(str(payload.get("job_id") or ""), payload, actor=actor)
        except KeyError as exc:
            return JSONResponse({"error": "not_found", "detail": str(exc)}, status_code=404)

    @app.get("/api/v1/resume/variants/{variant_id}")
    async def api_resume_variant(variant_id: str, _: str = Depends(require_session)):
        try:
            return get_resume_variant(variant_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)

    @app.patch("/api/v1/resume/variants/{variant_id}/source")
    async def api_resume_variant_source(variant_id: str, payload: dict, actor: str = Depends(require_write_session)):
        try:
            return update_resume_variant_source(variant_id, str(payload.get("source_text") or ""), actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)

    @app.post("/api/v1/resume/variants/{variant_id}/suggestions/{suggestion_id}")
    async def api_resume_accept_suggestion(variant_id: str, suggestion_id: str, actor: str = Depends(require_write_session)):
        try:
            return accept_resume_suggestion(variant_id, suggestion_id, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id, "suggestion_id": suggestion_id}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    @app.post("/api/v1/resume/variants/{variant_id}/accept-safe")
    async def api_resume_accept_safe(variant_id: str, actor: str = Depends(require_write_session)):
        try:
            return accept_all_safe_resume_suggestions(variant_id, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)

    @app.post("/api/v1/resume/variants/{variant_id}/compile")
    async def api_resume_compile(variant_id: str, actor: str = Depends(require_write_session)):
        try:
            return compile_resume_variant(variant_id, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)

    @app.get("/api/v1/resume/variants/{variant_id}/download")
    async def api_resume_download(variant_id: str, _: str = Depends(require_session)):
        try:
            document = get_resume_variant_download(variant_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)
        path = document.get("file_path")
        if path:
            return FileResponse(path, media_type=document.get("mime_type") or "application/octet-stream", filename=Path(path).name)
        return PlainTextResponse(str(document.get("content_text") or ""), media_type=document.get("mime_type") or "text/plain")

    @app.get("/api/v1/resume/variants/{variant_id}/ats")
    async def api_resume_variant_ats(variant_id: str, _: str = Depends(require_session)):
        try:
            return get_resume_variant_ats(variant_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)

    @app.post("/api/v1/resume/variants/{variant_id}/hm-audit")
    async def api_resume_hm_audit(variant_id: str, actor: str = Depends(require_write_session)):
        try:
            return generate_resume_hm_audit(variant_id, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "variant_id": variant_id}, status_code=404)

    @app.get("/api/v1/jobs/evaluation-queue")
    async def api_evaluation_queue(limit: int = 8, count_only: int = 0, _: str = Depends(require_session)):
        return get_evaluation_queue(limit=limit, count_only=bool(count_only))

    @app.get("/api/v1/jobs/{job_id}")
    async def api_job_detail(job_id: str, _: str = Depends(require_session)):
        try:
            return get_job(job_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)

    @app.get("/api/v1/jobs/{job_id}/resume")
    async def api_job_resume_workspace(job_id: str, _: str = Depends(require_session)):
        try:
            return get_job_resume_workspace(job_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)

    @app.post("/api/v1/jobs/{job_id}/prepare")
    async def api_prepare_job(job_id: str, payload: dict, actor: str = Depends(require_write_session)):
        try:
            return prepare_job_application(job_id, payload, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)

    @app.post("/api/v1/jobs/{job_id}/apply")
    async def api_apply_job(
        job_id: str,
        payload: dict,
        actor: str = Depends(require_write_session),
        x_jobradar_human_confirmed: str | None = Header(default=None),
    ):
        if actor.startswith("service:") and str(x_jobradar_human_confirmed or "").lower() != "true":
            return JSONResponse({"error": "human_confirmation_required"}, status_code=403)
        try:
            return mark_job_applied(job_id, payload, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)

    @app.post("/api/v1/jobs/{job_id}/status")
    async def api_job_status(job_id: str, payload: dict, actor: str = Depends(require_write_session)):
        try:
            return update_job_application_status(
                job_id,
                str(payload.get("stage") or ""),
                note=payload.get("note"),
                follow_up_at=payload.get("follow_up_at"),
                actor=actor,
            )
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)
        except ValueError:
            return JSONResponse({"error": "validation_error", "field": "stage"}, status_code=422)

    @app.post("/api/v1/followups/{application_id}/complete")
    async def api_complete_followup(application_id: str, payload: dict, actor: str = Depends(require_write_session)):
        try:
            return complete_followup(application_id, payload, actor=actor)
        except KeyError:
            return JSONResponse({"error": "not_found", "application_id": application_id}, status_code=404)

    @app.get("/api/v1/events")
    async def api_events(job_id: str | None = None, variant_id: str | None = None, stream: str = "automation", _: str = Depends(require_session)):
        async def event_stream():
            if stream == "resume":
                payload = get_resume_events(job_id=job_id, variant_id=variant_id)
                body = JSONResponse({"type": "resume_snapshot", "payload": payload}).body.decode("utf-8")
                yield f"event: resume_snapshot\ndata: {body}\n\n"
            else:
                payload = get_automation_status()
                body = JSONResponse({"type": "snapshot", "payload": payload}).body.decode("utf-8")
                yield f"event: snapshot\ndata: {body}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v1/jobs/{job_id}/evaluate")
    async def api_evaluate_job(job_id: str, payload: dict, actor: str = Depends(require_write_session)):
        try:
            report_number = payload.get("report_number")
            if report_number is None:
                raise ValueError("report_number required")
            return attach_evaluation(
                job_id,
                int(report_number),
                float(payload["career_ops_score"]) if payload.get("career_ops_score") is not None else None,
                str(payload["legitimacy"]) if payload.get("legitimacy") is not None else None,
                actor=actor,
            )
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)
        except (TypeError, ValueError):
            return JSONResponse({"error": "validation_error"}, status_code=422)

    @app.get("/api/v1/pipeline")
    async def api_pipeline(_: str = Depends(require_session)):
        return get_pipeline()

    @app.patch("/api/v1/pipeline/{job_id}/move")
    async def api_pipeline_move(job_id: str, payload: dict, _: str = Depends(require_write_session)):
        try:
            return move_pipeline_job(job_id, str(payload.get("to_stage") or ""))
        except KeyError:
            return JSONResponse({"error": "not_found", "job_id": job_id}, status_code=404)
        except ValueError:
            return JSONResponse({"error": "validation_error", "field": "to_stage"}, status_code=422)

    @app.post("/api/v1/scans", status_code=201)
    async def api_create_scan(payload: dict, _: str = Depends(require_write_session)):
        try:
            scan_id = create_scan(payload.get("mode", "portals"), payload.get("trigger", "manual"))
        except RuntimeError as exc:
            return JSONResponse({"error": "scan_running", "scan_id": str(exc)}, status_code=409)
        return {"scan_id": scan_id}

    @app.post("/api/v1/scans/{scan_id}/ingest")
    async def api_ingest_scan(scan_id: str, payload: dict, _: str = Depends(require_write_session)):
        return ingest_scan(scan_id, payload.get("candidates", []))

    @app.post("/api/v1/jobs/liveness")
    async def api_jobs_liveness(payload: dict, _: str = Depends(require_write_session)):
        return refresh_liveness(payload.get("job_ids"))

    @app.get("/api/v1/followups/due")
    async def api_followups_due(_: str = Depends(require_session)):
        return get_followups_due()

    @app.get("/api/v1/digest")
    async def api_digest(since: str = "24h", _: str = Depends(require_session)):
        return get_digest(since=since)

    @app.get("/api/v1/analytics")
    async def api_analytics(window: str = "90d", _: str = Depends(require_session)):
        return get_analytics(window=window)

    @app.get("/api/v1/scans/latest")
    async def api_latest_scan(_: str = Depends(require_session)):
        latest = get_latest_scan()
        if latest is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return latest

    @app.get("/api/v1/scans")
    async def api_list_scans(limit: int = 20, _: str = Depends(require_session)):
        return list_scans(limit=limit)

    @app.get("/api/v1/scans/{scan_id}")
    async def api_get_scan(scan_id: str, _: str = Depends(require_session)):
        try:
            return get_scan(scan_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "scan_id": scan_id}, status_code=404)

    @app.get("/api/db/summary")
    async def api_db_summary(_: str = Depends(require_session)):
        return get_db_summary()

    @app.get("/api/v1/health")
    async def api_health(_: str = Depends(require_session)):
        return get_health()

    @app.get("/api/v1/automation/status")
    async def api_automation_status(_: str = Depends(require_session)):
        return get_automation_status()

    @app.get("/api/v1/automation/runs")
    async def api_automation_runs(limit: int = 20, _: str = Depends(require_session)):
        return list_automation_runs(limit=limit)

    @app.get("/api/v1/automation/failures")
    async def api_automation_failures(_: str = Depends(require_session)):
        return list_automation_failures()

    @app.post("/api/v1/automation/failures/{failure_id}/retry")
    async def api_automation_retry_failure(failure_id: str, _: str = Depends(require_write_session)):
        try:
            return retry_ingest_failure(failure_id)
        except KeyError:
            return JSONResponse({"error": "not_found", "failure_id": failure_id}, status_code=404)

    return app


app = create_app()

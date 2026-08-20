# Environment Discovery — Job Radar

Generated: 2026-08-13 UTC
Spec: /home/saikali/HERMES_JOB_RADAR_MASTER_BUILD.md

## Summary

- Production hostname: jobs.saitejakavuri.com
- Cloudflare tunnel route exists and points to http://127.0.0.1:8765
- Current public status at discovery: HTTP 502 Bad Gateway
- Current local status on 127.0.0.1:8765 at discovery: no listener
- Located existing app repo: /home/saikali/openclaw-projects/job-hunter
- Located career-ops repo: /home/saikali/openclaw-projects/career-ops
- Existing app is not the expected FastAPI + Jinja2 + Datastar stack; it is a single-file Python http.server app in web/server.py serving inline HTML and /api/dashboard from SQLite
- No authentication was found in the current Job Radar app
- Hermes gateway is running and cron is healthy
- Hermes config timezone is America/Chicago; HERMES_TIMEZONE is now explicitly set in /home/saikali/.hermes/.env to America/Chicago for scheduler consistency even though the host system timezone remains UTC
- Existing legacy user crontab still points to /home/saikali/.openclaw/workspace/job-hunter, not the durable project path

## Decision gates from discovery

1. Authentication is absent and the app is publicly routed. Section 32 must be implemented early.
2. The current app is a toy/transitional implementation and does not satisfy the target architecture.
3. The Cloudflare route is already wired correctly to port 8765, so the rebuild should preserve that local origin port.
4. career-ops is installed and populated, so the adapter can be built against the live repo.
5. Hermes cron exists and the full Job Radar cron fleet is now installed under the active Hermes profile.

## Located paths

- Job Radar repo: /home/saikali/openclaw-projects/job-hunter
- Existing web entrypoint: /home/saikali/openclaw-projects/job-hunter/web/server.py
- Existing state dir: /home/saikali/openclaw-projects/job-hunter/state
- Existing SQLite DBs:
  - /home/saikali/openclaw-projects/job-hunter/state/staffing_v4.sqlite3
  - /home/saikali/openclaw-projects/job-hunter/state/v3.sqlite3
- career-ops root: /home/saikali/openclaw-projects/career-ops
- Cloudflare config: /etc/cloudflared/config.yml
- Hermes config: /home/saikali/.hermes/config.yaml
- Full raw discovery log: /home/saikali/.hermes/cache/terminal-output/out-1786597047-1217773-9450.log

## Host and runtime

- OS: Ubuntu 24.04.4 LTS
- Kernel: Linux 6.8.0-134-generic
- User: saikali (sudo, docker)
- Disk: root volume 915G with 768G free
- Memory: 6862 MiB RAM, 16383 MiB swap
- System timezone: UTC
- Hermes config timezone: America/Chicago

## Serving path for jobs.saitejakavuri.com

Cloudflare ingress contains:
- hostname: jobs.saitejakavuri.com
- service: http://127.0.0.1:8765

At discovery time:
- public curl returned HTTP 502 from Cloudflare
- cloudflared logs showed connection refused to 127.0.0.1:8765
- ss -tlnp showed no listener on 8765

Implication:
- the public route is already configured correctly, but the origin app was down during discovery

## Existing Job Radar implementation assessment

Repo layout indicates a durable project at /home/saikali/openclaw-projects/job-hunter.

Current web server implementation findings:
- Python stdlib BaseHTTPRequestHandler + HTTPServer
- Binds HOST=127.0.0.1, PORT=8765
- Serves only GET / and GET /api/dashboard
- Reads directly from state/staffing_v4.sqlite3
- Inlines HTML, CSS, and JS in one Python file
- No auth/session/login middleware
- No SSE
- No Datastar
- No FastAPI
- No migration framework

Current product naming in web/server.py is "Staffing Desk" / "Staffing Automation", not the specified Job Radar IA.

## Existing data and automation state

Current project contains:
- legacy incoming/processed ledgers
- state/staffing_v4.sqlite3 and state/v3.sqlite3
- tailored and tailored-v4 directories
- multiple helper scripts and logs under state/

Existing user crontab:
- 0 * * * * cd /home/saikali/.openclaw/workspace/job-hunter && /usr/bin/python3 scripts/run_hourly_v4_cycle.py >> /home/saikali/.openclaw/workspace/job-hunter/state/cron.log 2>&1

Implication:
- legacy automation still points at an old OpenClaw workspace path and must be replaced or retired during migration

## career-ops assessment

career-ops root exists at /home/saikali/openclaw-projects/career-ops.

Verified:
- reports/, data/, jds/, output/, config/, modes/, batch/ present
- templates/states.yml exists and matches canonical states
- data/applications.md is populated
- data/pipeline.md is populated
- reports/ contains existing report corpus
- node and npm are installed
- node doctor.mjs --json completed successfully
- node stats.mjs --json returned structured metrics

Implication:
- career-ops is installed and is the correct integration surface for the new adapter

## Hermes assessment

Verified:
- Hermes Agent v0.20.0
- Hermes gateway service active
- Hermes cron scheduler healthy
- one unrelated weekly backup job exists
- Job Radar cron fleet now installed:
  - f5ac4de67041 jobradar-liveness
  - 3a12a135f4c1 jobradar-discover
  - e4b9fb10d2b5 jobradar-sweep
  - 5c5cb62d49b9 jobradar-backup
  - 1be3c5266953 jobradar-evaluate
  - be1f1c900304 jobradar-brief
  - c2ec7dc3c012 jobradar-followup
  - 8ea0854af5c2 jobradar-weekly
- Hermes cron list resolves Job Radar `next_run_at` timestamps in America/Chicago local time (`-05:00` during current DST window).
- Durable smoke runs completed successfully for:
  - jobradar-liveness
  - jobradar-evaluate
  - jobradar-brief
  - jobradar-followup
- Live app verification now reports:
  - `/readyz` -> `{ok: true, database: ok, adapter: ok}`
  - `/api/v1/health` -> overall `status: ok`, `careerops_status: ok`, `scheduler_status: ok`
- End-to-end acceptance verification now additionally confirms:
  - live discover-to-ingest handoff works against current `career-ops` data
  - the latest accepted backfill/proof scan (`8e35de19228a404d82227e0499cbcb9b`) completed with `jobs_seen=2`, `jobs_added=2`, `jobs_updated=0`, `duplicates_merged=0`
  - `GET /api/v1/digest?since=24h` returns `new_jobs_count=2` and exposes both ingested jobs through Job Radar detail links
  - scan source rows were recorded for `jobicy.com` and `cisco.wd5.myworkdayjobs.com`
  - evaluation queue remains empty because both real ingested jobs currently score `personal_score=0`, `tier=D`; this is now a scoring/triage issue rather than a scheduler or ingest integration failure
  - after a targeted calibration patch and live reseed, two strong SOC-shaped jobs entered the queue at `personal_score=54`, `tier=B`
  - a live `jobradar-evaluate` cron run then drained the queue and attached `career_ops_report_number` values `74` and `75` to those jobs
  - the remaining behavior gap is narrower: `career_ops_score` / legitimacy were not written back for those seeded evaluations during the live cron run
  - `jobradar-brief` and `jobradar-weekly` have both been exercised directly with successful completed run records in Hermes cron history
  - a focused ad-hoc verification script under `/tmp/hermes-verify-*` confirmed the changed threshold behavior, live drained queue state, and persisted report-number attachments before cleanup
  - the app now deterministically hydrates `career_ops_score` and `career_ops_legitimacy` from the adapter-parsed career-ops report when `/api/v1/jobs/{id}/evaluate` is called with only `report_number`
  - this fallback was proven live by posting only `report_number=37` for two queued seeded jobs; both then persisted `career_ops_score=3.85` and `career_ops_legitimacy="High Confidence"`, and the queue drained to zero
  - the remaining runtime caveat is narrower still: the unattended `jobradar-evaluate` cron agent has shown unreliable queue consumption, including one saved run that surfaced a career-ops self-update prompt instead of executing the batch
- hermes cron create supports --workdir, --script, --no-agent, --model, --provider
- per-job timezone field does not exist in CLI help, matching the spec research note

Timezone finding:
- config.yaml sets timezone: America/Chicago
- HERMES_TIMEZONE env var is unset
- system timezone is UTC

Implication:
- scheduler should use the configured timezone, but created jobs must be verified by inspecting next_run_at

## Security findings

P0
- No authentication exists in the current app implementation
- Public hostname is routed through Cloudflare with no visible application login gate
- Current public endpoint is broken but still publicly reachable

P1
- Web layer reads SQLite directly and has no worker / adapter separation
- Current app has no obvious protection boundary between public route and private career data

## Discrepancies against the build spec

1. Expected stack was FastAPI + Jinja2 + Datastar SSE; actual stack is stdlib HTTPServer with inline HTML.
2. Expected authenticated private app; current app has no auth.
3. Expected live app at jobs.saitejakavuri.com; actual hostname is wired but origin was down at discovery time.
4. Expected cron-managed Job Radar automation; current automation is a legacy user crontab against an old workspace path.
5. sqlite3 CLI utility is absent on host, so DB inspection and backup work requiring sqlite will be done through Python's sqlite3 module.

## Key raw outputs captured

- Raw discovery output: /home/saikali/.hermes/cache/terminal-output/out-1786597047-1217773-9450.log
- Current public response from jobs.saitejakavuri.com: HTTP 502, body "error code: 502"
- Cloudflare route in /etc/cloudflared/config.yml points jobs.saitejakavuri.com to http://127.0.0.1:8765
- Existing web server source: /home/saikali/openclaw-projects/job-hunter/web/server.py
- Existing README: /home/saikali/openclaw-projects/job-hunter/README.md

## Superseded final-verification note

The original "Final verification update" block that used to live here was kept only as historical context from an earlier build checkpoint.
It is no longer the current source of truth because later phases changed the runtime materially:

- the full 8-job Hermes Job Radar cron fleet is now installed and verified live
- `/readyz` and `/api/v1/health` now reflect the real adapter + scheduler state
- discover, evaluate, brief, and weekly paths have all been exercised against the live runtime
- the app now supports deterministic score/legitimacy hydration from career-ops reports when only `report_number` is posted to `/api/v1/jobs/{id}/evaluate`

Use the newer Hermes assessment and end-to-end acceptance bullets above as the authoritative current state.

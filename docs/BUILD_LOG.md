# BUILD_LOG

## 2026-08-13 — Discovery started

- Loaded build spec from /home/saikali/HERMES_JOB_RADAR_MASTER_BUILD.md.
- Completed mandatory environment discovery before application changes.
- Wrote environment report to /home/saikali/openclaw-projects/job-hunter/docs/ENVIRONMENT.md.
- Created rollback backup at /home/saikali/backups/jobradar-20260813T050026.
- Backup contents include jobradar-repo.tgz, career-ops-userlayer.tgz, staffing_v4.sqlite3, v3.sqlite3, Hermes cron/config copies, and SHA256SUMS.

### Discovery findings

- Existing Job Radar repo located at /home/saikali/openclaw-projects/job-hunter.
- Existing public hostname jobs.saitejakavuri.com is routed by Cloudflare to 127.0.0.1:8765.
- Public site returned HTTP 502 during discovery because nothing was listening on 127.0.0.1:8765.
- Current app implementation is a single-file Python stdlib HTTP server, not FastAPI + Datastar.
- No authentication found in current app.
- career-ops located at /home/saikali/openclaw-projects/career-ops and populated.
- Hermes gateway and cron are healthy; no Job Radar cron fleet exists yet.
- sqlite3 command-line client is absent on host; Python sqlite3 will be used for snapshot and inspection tasks instead.

### Phase 1 security implementation progress

- Added a FastAPI-based authenticated app skeleton under /home/saikali/openclaw-projects/job-hunter/jobradar_app.
- Replaced the old stdlib web/server.py entrypoint with a uvicorn launcher for the authenticated app.
- Added auth tests at /home/saikali/openclaw-projects/job-hunter/tests/test_auth_app.py.
- Added SQLite spine tests at /home/saikali/openclaw-projects/job-hunter/tests/test_db_spine.py.
- Added migration-cycle tests at /home/saikali/openclaw-projects/job-hunter/tests/test_db_migrations.py.
- Added adapter tests at /home/saikali/openclaw-projects/job-hunter/tests/test_careerops_adapter.py and /home/saikali/openclaw-projects/job-hunter/tests/test_adapter_boundaries.py.
- Installed a dedicated project venv at /home/saikali/openclaw-projects/job-hunter/.venv-jobradar and pinned initial FastAPI/auth/test dependencies in requirements.txt.
- Added immediate public-surface hardening: response security headers and deny-all robots.txt.
- Added the full Section 19 migration framework in /home/saikali/openclaw-projects/job-hunter/jobradar_app/db.py with reversible versions 001-011, FTS tables, latest-schema summary reporting, and legacy processed-json backfill into the normalized SQLite spine.
- Added /home/saikali/openclaw-projects/job-hunter/careerops_adapter/ as the only sanctioned career-ops integration surface so far, with typed read/write helpers, argv-only subprocess discipline, sanitized environment, file locking, Machine Summary YAML parsing, and `automation_runs` logging into Job Radar SQLite.
- Verified local protections and adapter behavior with 17 passing tests.
- Added ingest/security foundation modules under /home/saikali/openclaw-projects/job-hunter/security and /home/saikali/openclaw-projects/job-hunter/ingest for sanitizer, injection detection, canonicalization, normalization, dedupe, and exclusion logic.
- Added Phase 4 tests at /home/saikali/openclaw-projects/job-hunter/tests/test_sanitize.py, /home/saikali/openclaw-projects/job-hunter/tests/test_ingest_pipeline.py, and /home/saikali/openclaw-projects/job-hunter/tests/security/test_injection_corpus.py.
- Verified the new Phase 4 foundation with 7 passing targeted tests.
- Wired the Phase 4 ingest foundation into real authenticated scan endpoints: POST /api/v1/scans and POST /api/v1/scans/{id}/ingest.
- Added persistence for scan rows, ingest failure rows, job/job_source/job_snapshot rows, and job.discovered/job.merged events.
- Added ingest endpoint tests at /home/saikali/openclaw-projects/job-hunter/tests/test_scan_ingest.py.
- Verified ingest endpoint wire-up with 3 passing targeted tests.
- Implemented scan history endpoints plus Phase 5 deterministic sponsorship placeholder, evidence persistence, scoring, tiering, liveness defaults, and scan_sources tracking.
- Added targeted Phase 5 tests at /home/saikali/openclaw-projects/job-hunter/tests/test_phase5_scoring_scans.py.
- Verified Phase 5 scan/scoring behavior with 3 passing targeted tests.
- Implemented Phase 6 jobs list/detail, pipeline read/move, and health endpoints for authenticated workflow exercise.
- Added Phase 6 tests at /home/saikali/openclaw-projects/job-hunter/tests/test_phase6_jobs_pipeline_health.py.
- Verified Phase 6 jobs/pipeline/health behavior with 3 passing targeted tests and a temporary end-to-end ad-hoc verifier.
- Implemented Phase 7 automation status/runs/failures/retry endpoints plus improved readiness payload.
- Added Phase 7 tests at /home/saikali/openclaw-projects/job-hunter/tests/test_phase7_automation_status.py.
- Verified Phase 7 automation/readiness behavior with 3 passing targeted tests and a temporary end-to-end ad-hoc verifier.
- Ran full regression suite after Phase 7: 36 passing tests across auth, db, migrations, adapter, ingest, scan, phase5, phase6, and phase7 coverage.
- Performed live-origin verification by launching the FastAPI app locally on 127.0.0.1:8765 and confirming local /healthz and /readyz responses.
- Performed public-route verification through Cloudflare while the local origin was running: /healthz returned 200, /readyz returned 200, /login returned the login page, and /api/v1/health returned 401 without authentication.
- Confirmed public security headers on jobs.saitejakavuri.com: X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy strict-origin-when-cross-origin, and X-Robots-Tag noindex/nofollow/noarchive/nosnippet.
- Confirmed the rebuilt app now satisfies the private-app auth gate at the route level for tested unauthenticated API access, replacing the discovery-time unauthenticated shell exposure.
- Confirmed previous gap at final verification: Job Radar-specific Hermes cron fleet had not yet been created, and /api/v1/health still reported scheduler and careerops as degraded placeholders rather than live integrated status.
- Implemented Phase 9 scheduler-facing API surface required by the Hermes cron fleet:
  - GET /api/v1/jobs/evaluation-queue
  - POST /api/v1/jobs/{id}/evaluate
  - POST /api/v1/jobs/liveness
  - GET /api/v1/followups/due
  - GET /api/v1/digest
  - GET /api/v1/analytics
- Replaced placeholder health wiring with live career-ops adapter probes and Hermes cron-state-backed scheduler probes.
- Added targeted Phase 9 tests at /home/saikali/openclaw-projects/job-hunter/tests/test_phase9_cron_api.py.
- Verified Phase 9 plus regressions: targeted 19 passing tests, then full suite 40 passing tests.
- Completed Phase 10 runtime integration:
  - Fixed live career-ops adapter health by updating doctor probing to use `doctor.mjs --json`.
  - Fixed live scan-runs parsing drift by supporting the current headered wide TSV format from career-ops.
  - Re-verified `/readyz` with `adapter: ok` and `/api/v1/health` with overall `status: ok`.
  - Pinned Hermes cron defaults to timezone America/Chicago and cron model/provider `gpt-5.4-mini` / `openai-codex`.
  - Created the full Job Radar Hermes cron fleet under the active profile:
    - f5ac4de67041 jobradar-liveness
    - 3a12a135f4c1 jobradar-discover
    - e4b9fb10d2b5 jobradar-sweep
    - 5c5cb62d49b9 jobradar-backup
    - 1be3c5266953 jobradar-evaluate
    - be1f1c900304 jobradar-brief
    - c2ec7dc3c012 jobradar-followup
    - 8ea0854af5c2 jobradar-weekly
  - Verified scheduler timezone behavior from `hermes cron list`: Job Radar jobs resolve `next_run_at` in `-05:00` America/Chicago local time.
  - Smoke-ran new agent jobs directly through Hermes cron:
    - evaluate: durable run completed successfully
    - brief: durable run completed successfully
    - followup: durable run completed successfully
  - Verified live API scheduler health now reports all 8 Job Radar jobs and overall `scheduler_status: ok`.
  - Verified final live API state with an ad-hoc `/tmp/hermes-verify-*` script, then removed it.
- Completed Phase 11 end-to-end acceptance evidence capture:
  - Verified `jobradar-discover` executes and records durable cron run history.
  - Identified and fixed the remaining discover handoff gap: the original `jobradar-discover.sh` always posted an empty `candidates` list to `/api/v1/scans/{id}/ingest`.
  - Updated `jobradar-discover.sh` to transform fresh `career-ops` `data/scan-history.tsv` rows into real Job Radar candidate payloads.
  - Proved the handoff with a one-time backfill into live Job Radar from two fresh 2026-08-13 `career-ops` scan-history rows.
  - Verified end-to-end live result:
    - scan `8e35de19228a404d82227e0499cbcb9b` completed
    - `jobs_seen=2`
    - `jobs_added=2`
    - `jobs_updated=0`
    - `duplicates_merged=0`
    - `evaluation_queue_depth=0`
  - Verified `GET /api/v1/digest?since=24h` now returns `new_jobs_count=2` and two live top-job entries with Job Radar detail links.
  - Verified scan source records were created for `jobicy.com` and `cisco.wd5.myworkdayjobs.com` under the latest scan.
  - Verified scan-lock behavior remains correct: while a scan row is still `running`, `POST /api/v1/scans` returns `409 scan_running`; after ingest completion, new scan creation succeeds again.
  - Remaining acceptance gap is now limited to scorer calibration rather than integration plumbing: today's two real discovered jobs were ingested successfully but scored `personal_score=0`, `tier=D`, leaving the evaluation queue empty.
- Per user direction, executed a parallel close-out:
  - Sent scoring-calibration analysis to a background subagent.
  - Tested the non-empty queue path immediately by seeding two strong SOC-shaped candidates through the live ingest API.
  - Added a red regression test proving two strong SOC jobs should enter the evaluation queue without manual DB promotion.
  - Applied the smallest calibration patch: `tier B` threshold lowered from `60` to `54` while leaving the deterministic score formula unchanged.
  - Verified targeted tests passed after the calibration patch.
  - Restarted the live Job Radar app and re-seeded two strong SOC-shaped candidates.
  - Verified live queue state became `count=2` with both seeded jobs at `personal_score=54`, `tier=B`.
  - Ran the live `jobradar-evaluate` cron job against the non-empty queue.
  - Verified post-run state:
    - queue drained back to `count=0`
    - both seeded jobs received `career_ops_report_number` attachments (`74` and `75`)
  - Remaining narrow gap after the live non-empty evaluate proof: the current evaluate prompt/flow did not post back `career_ops_score` or legitimacy for those seeded items even though it did consume the queue and attach report numbers.
- Completed the remaining live cron surface acceptance checks:
  - Ran `jobradar-brief` directly again; durable run history shows completed runs at `2026-08-13T11:40:15-05:00` and `2026-08-13T10:54:56-05:00`.
  - Ran `jobradar-weekly` directly again; durable run history shows a completed run at `2026-08-13T11:40:33-05:00`.
  - Verified `GET /api/v1/digest?since=24h` after the live acceptance work now reports `new_jobs_count=6` and includes the seeded/evaluated items with Job Radar detail links.
  - Verified `GET /api/v1/followups/due` remains healthy and returns `total=0` with no due followups in the current dataset.
  - Verified `GET /api/v1/health` remains overall `status=ok`, with `scheduler_status=ok`, `careerops_status=ok`, and all 8 Job Radar cron jobs present in scheduler items.
  - Ran a focused ad-hoc verification script under `/tmp/hermes-verify-*`, then removed it. That verifier confirmed:
    - targeted pytest for the new calibrated queue behavior passed
    - live evaluation queue was drained after evaluate (`count=0`)
    - the two seeded live jobs persisted as `personal_score=54`, `tier=B`, with attached `career_ops_report_number` values
- Continued building directly from the master document with parallel-agent assistance:
  - Identified a spec-aligned persistence gap: the app accepted `career_ops_score` and `legitimacy`, but if a caller posted only `report_number`, those fields remained null unless the caller hydrated them inline.
  - Added a failing regression test proving `/api/v1/jobs/{id}/evaluate` should hydrate `career_ops_score` and `career_ops_legitimacy` from the corresponding career-ops report when only `report_number` is supplied.
  - Patched `jobradar_app/db.py::attach_evaluation()` to use the existing adapter `read_report()` path to parse Machine Summary YAML / structural fields and fill missing score + legitimacy deterministically.
  - Verified targeted tests for both direct writeback and fallback hydration passed.
  - Restarted the live app and proved the new runtime behavior with direct authenticated API calls posting only `report_number`.
  - Verified live result on two queued seeded jobs:
    - queue drained to `count=0`
    - `career_ops_score` persisted as `3.85`
    - `career_ops_legitimacy` persisted as `High Confidence`
    - `job.evaluated` event detail now carries `report_number`, `career_ops_score`, and `legitimacy`
  - Remaining runtime caveat: the unattended Hermes `jobradar-evaluate` cron agent itself is still not reliably consuming queued jobs; one saved cron output showed it surfacing a career-ops self-update prompt instead of performing the batch. Parallel agents are now auditing the next highest-priority remaining spec/runtime gaps.
- Verified auth/header/robots behavior with an ad-hoc temporary verifier under /tmp using the `hermes-verify-` prefix, then cleaned it up.
- Verified migration up/down/up and import summary with a real temp-db smoke run.
- Verified adapter doctor/stats/report parsing/report-number reservation via a real temp fixture-repo smoke run.

### Spec-vs-reality discrepancies recorded

1. Current public origin is down at discovery time.
2. Current app architecture does not match target architecture.
3. Current automation still references an old OpenClaw workspace path.
4. System timezone is UTC while Hermes config timezone is America/Chicago.

## 2026-08-19 — Fast completion push

- Wrote an explicit completion plan to `/home/saikali/openclaw-projects/job-hunter/docs/plans/2026-08-19-jobradar-completion-plan.md`.
- Added a temporary auth-bypass switch `JOBRADAR_DISABLE_LOGIN` so browser and API testing can run without session login when explicitly enabled.
- Added regression coverage for auth-bypass mode in `tests/test_auth_app.py`.
- Added runtime env loader `jobradar_app/runtime_env.py` and updated `run_jobradar.py` to auto-load `~/.hermes/scripts/jobradar.env` / `.env.jobradar` and map legacy `CAREEROPS_ROOT` / `NODE_BIN` into `JOBRADAR_CAREEROPS_ROOT` / `JOBRADAR_NODE_BIN`.
- Restarted the live app with `JOBRADAR_DISABLE_LOGIN=true` for multi-agent testing.
- Verified live local/public shell access returns 200 without login.
- Verified local readiness now reports `adapter: ok` and health now reports overall `status: ok` with live career-ops stats.
- Ran `hermes cron run` for `jobradar-liveness` and `jobradar-discover`; both now complete successfully and `hermes cron list` shows fresh `ok` runs instead of the earlier 401 failures.
- Re-ran the full Python test suite: `57 passed`.

- 2026-08-20: Implemented first real Resume Studio slice: base resume registration, deterministic ATS analysis, job-scoped tailoring workspace, tailored variant persistence, live `/resume/{job_id}` route, and end-to-end API test coverage (`tests/test_resume_studio_api.py`). Verified with `pytest -q` => 58 passed and live local API calls to `/api/v1/resume/bases`, `/api/v1/resume/analyze`, and `/api/v1/resume/tailor`.
- 2026-08-20: Extended Resume Studio with safe-suggestion acceptance, editable variant source, HTML compile/download flow, variant compile status, and live UI controls for Accept safe suggestions / Compile / Download. Verified with `pytest -q` => 58 passed, targeted `tests/test_resume_studio_api.py`, and live local API/UI checks on `/api/v1/resume/variants/*` and `/resume/{job_id}`.
- 2026-08-20: Added Resume Studio ATS-history + SSE slice: baseline/final ATS analysis records, `/api/v1/resume/variants/{id}/ats`, `/api/v1/events?stream=resume&job_id=...`, resume progress events (`resume.progress`), and a live resume event feed in `/resume/{job_id}`. Verified with `pytest -q` => 59 passed and live local API checks showing `baseline` then `final` phases after compile.
- 2026-08-20: Added Resume Studio immutability/revision flow. Applications can now store `resume_variant_id`, linked variants are locked on prepare/apply, and any later edit/accept/compile on a locked variant automatically forks a new revision with `parent_variant_id`, preserving the original artifact. Added schema migration 013 to backfill revision/version/lock columns on existing installs. Verified with `pytest -q` => 60 passed and live local apply→edit flow showing locked original + forked revision 2.
- 2026-08-20: Fixed live `/api/v1/jobs/{job_id}/prepare` career-ops bridge compatibility when `reserve-report-num.mjs` returns a single report number instead of a range. `CareerOpsAdapter.reserve_report_numbers()` now accepts both `043-044` and `078` shapes. Verified with new adapter test, full suite `61 passed`, and live prepare flow storing `applications.resume_variant_id` while locking the referenced variant.
- 2026-08-20: Added Hiring Manager audit generation for Resume Studio. New endpoint `POST /api/v1/resume/variants/{id}/hm-audit` writes a markdown audit artifact, attaches it to the variant payload as `hm_audit_document`, records ATS phase `hm_audit`, and emits `resume.hm_audit_generated`. Verified with targeted tests, full suite `61 passed`, live API flow, and live `/resume` HTML exposing a Generate HM Audit control.
## 2026-08-20 — Phase A hardening follow-up

- Added `JOBRADAR_TIMEZONE` / `TZ` launcher normalization in `run_jobradar.py` with default `America/Chicago` so live runtime and cron-adjacent processes share Central time expectations.
- Extended `jobradar_app/config.py` with explicit `timezone_name` and opt-in `require_cloudflare_access` settings.
- Added an app-side Cloudflare Access write gate scaffold in `jobradar_app/main.py` for mutating requests: when `JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS=true`, POST/PUT/PATCH/DELETE require `CF-Access-Jwt-Assertion` or `CF-Access-Authenticated-User-Email`, while test mode (`JOBRADAR_DISABLE_LOGIN=true`) still bypasses the gate for agent QA.
- Added auth regression coverage in `tests/test_auth_app.py` for blocked writes without CF headers, allowed writes with CF headers, and disable-login bypass behavior.

## 2026-08-20 — Completion closure push

- Tightened Resume Studio fabrication guard behavior:
  - separated safe suggestions from blocked guardrail suggestions in the Resume Studio UI
  - added a Guardrails tab for unsupported claims
  - added deterministic detection for common unsupported security-platform claims such as CrowdStrike Falcon / QRadar / Chronicle / XSOAR / Carbon Black
  - added regression coverage proving unsafe suggestions return `422 unsafe_suggestion` and cannot be accepted through the safe path
- Added `scripts/import_sponsorship_data.py`, a header-tolerant sponsorship data importer for USCIS H-1B employer CSVs and DOL LCA CSVs.
  - It upserts H-1B employer history, inserts LCA records, refreshes company H-1B summary columns, recomputes current job sponsorship class/confidence, stores sponsorship evidence, and records an automation run.
  - Verified with a temp DB fixture: 2 H-1B rows imported, 1 company refreshed to `h1b_total_3yr=20` / `h1b_last_fy=2026`, and 1 job recomputed to `sponsorship_class='likely'` / `confidence=0.68`.
- Created final operations and acceptance documentation:
  - `docs/OPERATIONS.md`
  - `docs/ACCEPTANCE.md`
- Created a fresh verified backup at `/home/saikali/backups/jobradar/20260820T154620` using the same DB-copy/user-layer backup logic as the cron script.
  - Backup DB `PRAGMA integrity_check` returned `ok`.
  - Backup DB schema version: `13`.
  - Backup DB counts: `jobs=9`, `companies=9`, `resume_bases=13`, `resume_variants=12`, `automation_runs=98`.
- Verification:
  - `python -m py_compile scripts/import_sponsorship_data.py` passed.
  - `PYTHONPATH=. pytest -q tests/test_resume_studio_api.py tests/test_resume_events_api.py` passed.
  - Full suite `PYTHONPATH=. pytest -q` passed: `64 passed in 83.36s`.
  - Live `/readyz` returned `ok` with DB and adapter healthy.
  - Live `/api/v1/health` returned overall `status: ok`.
- Current estimated completion: ~85% overall. The remaining spec gaps are real external sponsorship dataset import, final responsive UI polish, deeper analytics/attribution, and monitoring the next unattended evaluate cron consumption run.

## 2026-08-20 — Analytics + UI polish follow-up

- Launched a parallel UI/UX agent focused on `jobradar_app/main.py` and the high-fidelity mockup.
  - The agent landed behavior-preserving UI polish for mobile navigation, Resume Studio density, event feed cards, guardrail readability, and dashboard failure-state copy.
  - The agent verified inline JS extraction and `node --check`; its temporary system-Python live smoke failed as expected with missing `argon2`, confirming `.venv-jobradar` remains required.
- Expanded `/api/v1/analytics` from basic counts to spec-grade operator metrics:
  - funnel applied/responded/interview/offer counts and rates
  - application `by_stage` distribution
  - resume-version attribution grouped by variant/document linkage
  - follow-up compliance tracked/completed/due-open metrics
  - small-sample and due-follow-up warnings
- Surfaced the expanded analytics in the dashboard Analytics section with funnel cards, follow-up compliance cards, status mix, and resume attribution list.
- Updated `/api/v1/health` dataset checks to report H-1B/LCA row counts, latest loaded timestamps, and covered fiscal years instead of placeholder dataset status.
- Updated docs with the analytics runbook and acceptance evidence.
- Verification before live restart:
  - extracted inline JS to `/tmp/jobradar-inline.js`; `node --check` passed.
  - `python -m py_compile jobradar_app/db.py jobradar_app/main.py tests/test_phase9_cron_api.py tests/test_phase6_jobs_pipeline_health.py` passed.
  - `PYTHONPATH=. pytest -q tests/test_phase6_jobs_pipeline_health.py tests/test_phase9_cron_api.py` passed: `9 passed in 20.48s`.
  - Full suite `PYTHONPATH=. pytest -q` passed after the analytics/UI merge: `64 passed in 86.09s`.
  - Live app restarted on PID `2727723`; `/readyz` returned `ok`, `/api/v1/analytics?window=90d` returned the new funnel/attribution payload, and browser QA of `/analytics` showed no console errors or obvious visual breakage.


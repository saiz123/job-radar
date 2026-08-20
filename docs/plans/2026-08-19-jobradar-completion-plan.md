# Job Radar Completion Plan

> **For Hermes:** Use subagent-driven-development for parallel audits/reviews, but implement directly when the path is already clear and verification is cheap.

**Goal:** Finish the remaining high-value spec gaps in Job Radar as fast as possible while keeping the app runnable for agent testing.

**Current live status:** auth bypass is temporarily enabled via `JOBRADAR_DISABLE_LOGIN=true`; full test suite is green (`55 passed`); local/public shell loads; cron fleet exists; current remaining blockers are runtime adapter/env wiring, sponsorship dataset loading, Resume Studio depth, and final ops/hardening acceptance work.

**Architecture:** Keep the current FastAPI + SQLite + career-ops adapter architecture. Do not rewrite the app. Finish the remaining spec by closing the runtime/env gaps first, then filling the missing feature surfaces in the existing schema/API/UI, then landing acceptance/ops proof.

**Tech Stack:** FastAPI, uvicorn, SQLite, pytest, Hermes cron, career-ops Node scripts.

---

## Phase 0: Temporary multi-agent testing mode

### Task 0.1: Keep login disabled intentionally and visibly
**Objective:** Allow other agents to hit the UI/API without the browser login while making the temporary state explicit.

**Files:**
- Modify: `jobradar_app/config.py`
- Modify: `jobradar_app/main.py`
- Test: `tests/test_auth_app.py`

**Done when:**
- `JOBRADAR_DISABLE_LOGIN=true` allows browser + API access without a session
- default behavior remains auth-on when env flag is absent/false
- test coverage proves both modes

**Verification:**
- `source .venv-jobradar/bin/activate && PYTHONPATH=. pytest -q tests/test_auth_app.py`
- `curl -fsS http://127.0.0.1:8765/api/v1/jobs | python3 -m json.tool | head`

### Task 0.2: Restart live app with the right env
**Objective:** Ensure the live process actually has the env required for agent testing and cron access.

**Files:**
- Runtime env: `~/.hermes/scripts/jobradar.env`
- Entry point: `run_jobradar.py`

**Commands:**
```bash
kill <old-pid>
set -a
source ~/.hermes/scripts/jobradar.env
set +a
export JOBRADAR_BIND_HOST=127.0.0.1
export JOBRADAR_BIND_PORT=8765
export JOBRADAR_SESSION_DIR=/home/saikali/openclaw-projects/job-hunter/state/sessions
export JOBRADAR_DISABLE_LOGIN=true
source .venv-jobradar/bin/activate
python run_jobradar.py
```

**Done when:**
- local `/` returns 200
- public `/` returns 200
- other agents can test without password login

---

## Phase 1: Fix runtime env drift and cron/API reliability

### Task 1.1: Make app startup load the same env contract the cron scripts assume
**Objective:** Eliminate `careerops_not_configured` and service-token drift by unifying env loading.

**Files:**
- Modify: `run_jobradar.py`
- Modify: `jobradar_app/config.py`
- Modify: `docs/BUILD_LOG.md`
- Optional create: `jobradar.env.example`

**Implementation notes:**
- Prefer loading `~/.hermes/scripts/jobradar.env` (or a project-local equivalent) from the launcher when variables are missing.
- Do not hardcode secrets in the repo.
- Ensure the live app gets at least:
  - `JOBRADAR_SERVICE_TOKEN`
  - `JOBRADAR_CAREEROPS_ROOT`
  - `JOBRADAR_NODE_BIN`
  - `JOBRADAR_DB_PATH`
  - `JOBRADAR_IMPORT_DIR`

**Done when:**
- `/readyz` shows `adapter: ok`
- `/api/v1/health` shows `careerops.status = ok`

**Verification:**
- `curl -fsS http://127.0.0.1:8765/readyz`
- `curl -fsS http://127.0.0.1:8765/api/v1/health | python3 -m json.tool`

### Task 1.2: Prove cron scripts can talk to the live API again
**Objective:** Remove the 401 failures from `jobradar-liveness` and `jobradar-discover`.

**Files:**
- Inspect/modify if needed: `~/.hermes/scripts/jobradar-discover.sh`
- Inspect/modify if needed: `~/.hermes/scripts/jobradar-liveness.sh`
- Inspect/modify if needed: `~/.hermes/scripts/jobradar.env`
- Modify: `docs/BUILD_LOG.md`

**Done when:**
- `hermes cron run jobradar-liveness` succeeds
- `hermes cron run jobradar-discover` succeeds
- `hermes cron list` no longer shows fresh 401 failures for those jobs

**Verification:**
```bash
hermes cron run f5ac4de67041
hermes cron run 3a12a135f4c1
hermes cron list
```

### Task 1.3: Add one runtime smoke test script
**Objective:** Make repeated live verification cheap.

**Files:**
- Create: `scripts/verify_runtime.py`
- Modify: `docs/OPERATIONS.md`

**Script should check:**
- `/healthz`
- `/readyz`
- `/api/v1/health`
- public `/`
- evaluation queue count
- cron summary

---

## Phase 2: Finish the missing sponsorship intelligence runtime path

### Task 2.1: Add dataset import commands for USCIS H-1B history
**Objective:** Move sponsorship intelligence from schema-only to live data-backed.

**Files:**
- Modify: `jobradar_app/db.py`
- Create: `scripts/load_uscis_h1b.py`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/BUILD_LOG.md`

**Implementation notes:**
- Load CSV into `h1b_employer_stats`
- keep import idempotent
- record `loaded_at` and source URL metadata

**Done when:**
- `h1b_employer_stats` row count > 0 in live DB
- `/api/v1/health` or analytics surfaces loaded FY coverage
- ingest for matching companies produces `h1b_history` evidence

### Task 2.2: Add optional OFLC/LCA loader behind a flag
**Objective:** Support the spec’s optional enrichment path without blocking core completion.

**Files:**
- Create: `scripts/load_oflc_lca.py`
- Modify: `jobradar_app/db.py`
- Modify: `jobradar_app/main.py` or settings endpoint if needed

**Done when:**
- loader can import sample/real file into `lca_records`
- enrichment remains off unless explicitly enabled

---

## Phase 3: Build the real Resume Studio feature surface

### Task 3.1: Expose base resume + variant + suggestion APIs
**Objective:** Turn the existing resume tables into a usable feature, not dead schema.

**Files:**
- Modify: `jobradar_app/db.py`
- Modify: `jobradar_app/main.py`
- Create tests: `tests/test_resume_studio_api.py`

**Endpoints to add:**
- `GET /api/v1/resume/bases`
- `POST /api/v1/resume/bases`
- `GET /api/v1/resume/variants`
- `POST /api/v1/jobs/{job_id}/resume/generate`
- `GET /api/v1/jobs/{job_id}/resume`
- `POST /api/v1/resume/variants/{variant_id}/suggestions/apply`

**Done when:**
- live DB shows non-zero `resume_bases`, `resume_variants`, `resume_suggestions` after one real flow

### Task 3.2: Wire the generation path to real career-ops artifacts
**Objective:** Produce report-linked resume artifacts instead of placeholder document rows.

**Files:**
- Modify: `careerops_adapter/adapter.py`
- Modify: `jobradar_app/db.py`
- Modify: `jobradar_app/main.py`
- Inspect integration helpers under `scripts/` and `career-ops/`

**Implementation notes:**
- Prefer deterministic artifact registration over a new generation engine from scratch
- store lineage: base resume -> variant -> job/application
- persist artifact path, source report number, ATS notes, suggestion receipt

### Task 3.3: Upgrade the Resume page UI from shell to workflow
**Objective:** Make `/resume` a real operator surface.

**Files:**
- Modify: `jobradar_app/main.py`

**Must show:**
- base resume status
- per-job variant list
- ATS fit summary
- generated suggestions
- links to resume / cover letter / answers / report

**Verification:**
- browser/API smoke with at least one real generated variant

---

## Phase 4: Complete analytics and workflow acceptance gaps

### Task 4.1: Lift analytics from basic counts to spec-grade metrics
**Objective:** Surface actionable application analytics with the small-sample rule.

**Files:**
- Modify: `jobradar_app/db.py`
- Modify: `jobradar_app/main.py`
- Create tests: `tests/test_analytics_metrics.py`

**Add:**
- funnel metrics
- stage conversion counts
- resume-version attribution
- follow-up compliance
- small-sample warnings

### Task 4.2: Finish applications/interviews/documents operational depth
**Objective:** Ensure every document and stage move is traceable.

**Files:**
- Modify: `jobradar_app/db.py`
- Modify: `jobradar_app/main.py`
- Extend: `tests/test_phase15_workflow_api.py`
- Extend: `tests/test_phase16_resources.py`

**Done when:**
- one real job can move through prepare -> applied -> responded/interview with attached artifact lineage

---

## Phase 5: Final hardening, docs, and acceptance proof

### Task 5.1: Write the missing operations guide
**Objective:** Satisfy section 40 explicitly.

**Files:**
- Create: `docs/OPERATIONS.md`

**Must include:**
- architecture overview
- env vars
- local dev
- deploy/update
- DB ops
- career-ops integration boundaries
- Hermes cron fleet
- manual scan path
- troubleshooting
- backup/restore drill
- update procedure for career-ops

### Task 5.2: Run and document restore drill
**Objective:** Prove the backup path actually works.

**Files:**
- Modify: `docs/BUILD_LOG.md`
- Modify: `docs/OPERATIONS.md`

**Done when:**
- backup path documented
- restore rehearsal date recorded
- integrity check command recorded and run

### Task 5.3: Build the final acceptance checklist evidence
**Objective:** Close the loop against the master build file.

**Files:**
- Create: `docs/ACCEPTANCE.md`
- Modify: `docs/BUILD_LOG.md`

**For each remaining AT block:**
- record command run
- record result
- record evidence path or screenshot/log
- record pass/fail

---

## Fastest execution order

1. **Phase 0** — auth bypass + live restart
2. **Phase 1** — env/adapter/cron reliability
3. **Phase 3** — Resume Studio (largest spec weight still missing)
4. **Phase 2** — sponsorship dataset loading
5. **Phase 4** — analytics/workflow depth
6. **Phase 5** — ops docs / restore drill / acceptance closure

---

## Mandatory verification commands

```bash
source .venv-jobradar/bin/activate
PYTHONPATH=. pytest -q
curl -fsS http://127.0.0.1:8765/readyz
curl -fsS http://127.0.0.1:8765/api/v1/health | python3 -m json.tool
curl -fsS https://jobs.saitejakavuri.com/ | head
hermes cron list
sqlite3 /home/saikali/openclaw-projects/job-hunter/state/jobradar.sqlite3 '.tables'   # if sqlite3 exists
```

When `sqlite3` CLI is unavailable, use Python’s stdlib `sqlite3` instead.

---

## Current exit target

A credible “complete enough” finish for this push means:
- agent-test mode live without browser login
- runtime adapter healthy
- cron 401s eliminated
- at least one real resume base + variant + suggestions flow in the app
- sponsorship dataset loader landed and exercised
- operations guide + acceptance evidence written
- full test suite green

# Job Radar Operations Guide

Last verified: 2026-08-20T15:50:15+00:00

## 1. Architecture overview

Job Radar is Sai's private entry-level cybersecurity job-search operations dashboard.

Main runtime pieces:

- **FastAPI app:** `jobradar_app/main.py`
- **Launcher:** `run_jobradar.py`
- **SQLite spine:** `state/jobradar.sqlite3` by default, or `JOBRADAR_DB_PATH`
- **Career-ops integration:** configured by `JOBRADAR_CAREEROPS_ROOT`
- **Hermes cron fleet:** `jobradar-*` scheduled jobs/scripts
- **Resume Studio artifacts:** stored beside the DB under `resume_variants/`
- **Backups:** `JOBRADAR_BACKUP_DIR`, currently verified at `/home/saikali/backups/jobradar/20260820T154620`

The app is intentionally server-rendered with inline HTML/CSS/JS in `jobradar_app/main.py` for speed and simple local ownership.

## 2. Runtime environment

Preferred launch from the project root:

```bash
source .venv-jobradar/bin/activate
export JOBRADAR_DISABLE_LOGIN=true          # temporary agent-test mode only
export JOBRADAR_BIND_HOST=127.0.0.1
export JOBRADAR_BIND_PORT=8765
export JOBRADAR_SESSION_DIR=/home/saikali/openclaw-projects/job-hunter/state/sessions
python run_jobradar.py
```

Do **not** use plain `python3 run_jobradar.py` outside the project venv; the system Python does not carry the app dependencies such as `argon2`.

`run_jobradar.py` loads `~/.hermes/scripts/jobradar.env` / `.env.jobradar` and maps legacy variables where needed.

Important env vars:

| Variable | Purpose |
| --- | --- |
| `JOBRADAR_DB_PATH` | SQLite DB path |
| `JOBRADAR_IMPORT_DIR` | processed ingest artifact directory |
| `JOBRADAR_CAREEROPS_ROOT` | career-ops repo root |
| `JOBRADAR_NODE_BIN` | optional Node binary override |
| `JOBRADAR_SERVICE_TOKEN` | API token for scripts/cron |
| `JOBRADAR_DISABLE_LOGIN` | temporary test-mode browser/session bypass |
| `JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS` | opt-in write gate requiring CF Access headers |
| `JOBRADAR_TIMEZONE` / `TZ` | defaults to `America/Chicago` |
| `JOBRADAR_BACKUP_DIR` | backup output root |

## 3. Local health checks

```bash
curl -fsS http://127.0.0.1:8765/readyz
curl -fsS http://127.0.0.1:8765/api/v1/health | python3 -m json.tool
```

Expected current readiness shape:

- `ok: true`
- `database: ok`
- `adapter: ok`
- bind `127.0.0.1:8765`

## 4. Public/private access model

Current agent-testing mode can bypass browser login with `JOBRADAR_DISABLE_LOGIN=true`.

Secure production posture:

1. set `JOBRADAR_DISABLE_LOGIN=false`
2. keep a strong `JOBRADAR_SECRET_KEY`
3. keep `JOBRADAR_PASSWORD_HASH` populated
4. enable Cloudflare Access upstream
5. optionally set `JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS=true` so mutating requests require either:
   - `CF-Access-Jwt-Assertion`, or
   - `CF-Access-Authenticated-User-Email`

Readiness endpoints stay unauthenticated for deployment checks. Mutating APIs remain CSRF/session/service-token protected unless test mode is explicitly enabled.

## 5. Career-ops integration boundaries

Job Radar does not replace career-ops. It uses career-ops for deterministic scan/evaluation artifacts and stores stable references in the SQLite spine.

Important behavior:

- report numbers can be reserved from career-ops
- `/prepare` links application/resume variants to report artifacts
- score/legitimacy can be hydrated from report numbers
- Resume Studio records variant/document/audit lineage in Job Radar DB

Career-ops user-layer backup includes:

- `cv.md`
- `portals.yml`
- `config/`
- `data/`
- `reports/`
- `jds/`
- `output/`
- mode profile/custom files when present

## 6. Resume Studio runbook

Primary browser route:

```text
/resume/{job_id}
```

Core API flow:

```bash
GET  /api/v1/resume/bases
POST /api/v1/resume/bases
POST /api/v1/resume/analyze
POST /api/v1/resume/tailor
GET  /api/v1/jobs/{job_id}/resume
POST /api/v1/resume/variants/{variant_id}/suggestions/{suggestion_id}
POST /api/v1/resume/variants/{variant_id}/accept-safe
PATCH /api/v1/resume/variants/{variant_id}/source
POST /api/v1/resume/variants/{variant_id}/compile
GET  /api/v1/resume/variants/{variant_id}/download
GET  /api/v1/resume/variants/{variant_id}/ats
POST /api/v1/resume/variants/{variant_id}/hm-audit
GET  /api/v1/events?stream=resume&job_id={job_id}
```

Invariants:

- unsafe/fabrication-guarded suggestions cannot be accepted through the safe-suggestion endpoint
- variants linked to applications are locked
- edits/accept/compile on locked variants fork a new revision instead of mutating the historical artifact
- HM audits are stored as documents and attached to the variant payload

## 7. Sponsorship data operations

Schema support is present for:

- `h1b_employer_stats`
- `lca_records`
- company `h1b_total_3yr` / `h1b_last_fy`
- per-job `sponsorship_evidence`

Importer:

```bash
source .venv-jobradar/bin/activate
python scripts/import_sponsorship_data.py --h1b /path/to/uscis-employer-data.csv --source-url 'USCIS Employer Data Hub FY2026'
python scripts/import_sponsorship_data.py --lca /path/to/dol-lca.csv --fiscal-year 2026 --source-url 'DOL LCA FY2026'
python scripts/import_sponsorship_data.py --refresh-only
```

Large DOL XLSX releases can be downloaded/imported with the browser-like downloader and fast calamine importer:

```bash
source .venv-jobradar/bin/activate
python scripts/download_lca.py
PYTHONPATH=. python scripts/import_lca_xlsx_calamine.py \
  data/sponsorship/LCA_Disclosure_Data_FY2026_Q3.xlsx \
  --fiscal-year 2026 \
  --replace-fiscal-year \
  --source-url 'https://www.dol.gov/media/LCA_Disclosure_Data_FY2026_Q3.xlsx'
```

The importer is header-tolerant, upserts H-1B employer rows, inserts LCA rows, refreshes company summary fields, recomputes sponsorship class/confidence for current jobs, and writes an `automation_runs` audit row.

Verified real-data state on 2026-08-20:

- USCIS H-1B employer rows: `136,885`
- DOL LCA rows: `437,496`
- fiscal years visible in health: `[2026, 2023, 2022, 2021]`
- `/api/v1/health` reports `checks.datasets.status=ok`
- SQLite integrity check: `ok`

## 8. Analytics and attribution operations

Endpoint:

```bash
curl -fsS http://127.0.0.1:8765/api/v1/analytics?window=90d | python3 -m json.tool
```

Returned operational fields:

- `funnel`: applied/responded/interview/offer counts plus response/interview/offer rates
- `by_stage`: application-stage distribution
- `resume_attribution`: applications/responses/interviews/offers grouped by resume variant or linked resume document
- `followup_compliance`: tracked/completed/due-open follow-up counts and completion rate
- `warnings`: small-sample and due-follow-up operator warnings

Interpretation rules:

- `funnel.small_sample=true` means rates are directional only; do not over-optimize resume variants from fewer than 10 applications.
- `followup_compliance.due_open > 0` should trigger manual review of `/api/v1/followups/due` or the Applications tab.
- `resume_attribution` is intentionally conservative: unlinked applications are grouped as `no_resume_variant` rather than inferred.

## 9. Hermes cron fleet

Current active Job Radar jobs:

- `jobradar-liveness`
- `jobradar-discover`
- `jobradar-sweep`
- `jobradar-backup`
- `jobradar-evaluate`
- `jobradar-brief`
- `jobradar-followup`
- `jobradar-weekly`

Inspect:

```bash
hermes cron list
```

Scripts live under:

```text
/home/saikali/.hermes/scripts/jobradar-*.sh
```

Delivery is intentionally local-only for Job Radar automations, matching Sai's preference to keep job-search automation website/local-only and not Telegram-notified.

`jobradar-evaluate` is configured as a script-only (`no_agent=true`) job using `jobradar-evaluate.sh`. It consumes `/api/v1/jobs/evaluation-queue`, writes conservative career-ops markdown reports, attaches report number/score/legitimacy through the Job Radar API, and stores an `automation_runs` audit row. Manual proof on 2026-08-20 consumed queue `2 -> 0` and persisted report numbers `84` and `85` with score `3.16` / legitimacy `High Confidence`.

## 10. Backup procedure

The backup process creates:

- SQLite copy via `VACUUM INTO` after `PRAGMA integrity_check`
- career-ops user-layer tarball

Manual equivalent used successfully on 2026-08-20:

```bash
python3 - <<'PY'
from pathlib import Path
import os, shlex, sqlite3, tarfile, time
# parse ~/.hermes/scripts/jobradar.env for JOBRADAR_DB_PATH, CAREEROPS_ROOT, JOBRADAR_BACKUP_DIR
# run PRAGMA integrity_check, VACUUM INTO backup/jobradar.db, and tar selected career-ops user-layer paths
PY
```

Verified backup path:

```text
/home/saikali/backups/jobradar/20260820T154620
```

Verified contents:

- `jobradar.db` size: 782336 bytes
- `careerops-userlayer.tgz` size: 1188043 bytes

## 11. Restore drill

Verified on 2026-08-20:

- backup DB: `/home/saikali/backups/jobradar/20260820T154620/jobradar.db`
- `PRAGMA integrity_check`: `ok`
- schema version: `13`
- restored DB counts inspected from the backup copy:
  - `jobs=9`
  - `companies=9`
  - `resume_bases=13`
  - `resume_variants=12`
  - `automation_runs=98`

Basic restore steps:

1. stop the live app or point a test runtime at a copy
2. copy `jobradar.db` to the desired DB path
3. extract `careerops-userlayer.tgz` into the career-ops root or a rehearsal clone
4. start app with venv launcher
5. run `/readyz`, `/api/v1/health`, and a browser smoke check

## 12. Verification commands before handoff

```bash
source .venv-jobradar/bin/activate
PYTHONPATH=. pytest -q
python -m py_compile jobradar_app/main.py jobradar_app/db.py scripts/import_sponsorship_data.py
python - <<'PY'
from pathlib import Path
import re
text=Path('jobradar_app/main.py').read_text()
script=re.search(r'<script>([\s\S]*)</script>', text.split('APP_HTML = """',1)[1].split('"""',1)[0]).group(1)
Path('/tmp/jobradar-inline.js').write_text(script)
PY
node --check /tmp/jobradar-inline.js
curl -fsS http://127.0.0.1:8765/readyz
curl -fsS http://127.0.0.1:8765/api/v1/health | python3 -m json.tool
```

Most recent full suite result: `64 passed`.

## 13. Troubleshooting

- `ModuleNotFoundError: argon2`: use `.venv-jobradar/bin/python` or activate `.venv-jobradar`; do not run with system Python.
- Blank app shell after UI edits: extract served inline JS and run `node --check`; escaped regex newlines are the common failure mode.
- Public site still old: verify local route, tunnel route, browser console, and cache-busting URL before blaming cache.
- Cron 401: check service token/env loading boundary in `~/.hermes/scripts/jobradar.env` and `run_jobradar.py`.
- Sponsorship stuck at `not_stated`: verify H-1B data was imported, company normalized names match, then run `scripts/import_sponsorship_data.py --refresh-only`.
- Career-ops report reserve failures: verify adapter accepts both range output (`043-044`) and single-number output (`078`).

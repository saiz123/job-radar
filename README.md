# Job Hunter Automation

This folder contains a lightweight job-hunting operating system for Sai's entry-level cybersecurity search.

## What it does
- stores the candidate profile and master resume
- scores jobs against a defensible rubric
- keeps a queue of reviewed jobs
- generates Telegram-ready alert text for strong matches
- can dispatch outbox alerts through OpenClaw Telegram with sent-state dedupe
- provides a manager runbook so Jody can operate the search consistently

## Main files
- `config/profile.json` — candidate preferences and thresholds
- `resumes/master_resume.md` — canonical resume source
- `docs/scoring.md` — human-readable scoring rubric
- `templates/telegram_alert.md` — alert format
- `state/jobs.ndjson` — reviewed jobs ledger
- `state/shortlist.ndjson` — strong matches only
- `incoming/` — drop raw job descriptions here
- `processed/` — archived scored job records
- `manager/OPERATIONS.md` — how to run and maintain the system
- `manager/TAILORING_GUIDE.md` — rules for truthful resume tailoring

## Operating model
1. collect jobs into `incoming/` or source them through fetch/discovery helpers
2. score each job with `python3 scripts/run_pipeline.py --scoring-mode v2`
3. append reviewed results into `state/jobs.ndjson`
4. write direct strong matches into `state/shortlist.ndjson`
5. promote strong watch jobs with `python3 scripts/promote_watch_jobs.py --promotion-mode v2`
6. build Tier A promoted alerts into `state/outbox.ndjson` with `python3 scripts/build_promoted_alerts.py --alert-mode v2`
7. optionally run `python3 scripts/dispatch_outbox.py --send --target <telegram-target>` to deliver queued alerts and record receipts in `state/sent_alerts.ndjson`
8. if Sai replies YES on a specific job, create tailored materials in `tailored/<company>-<role>/`

## Notes
This scaffold is intentionally file-first so it can run even when direct command execution is flaky. The current canonical flow is staged:
- pipeline scores and writes ledgers
- promotion curates strong watch jobs into `state/promoted_shortlist.ndjson`
- alert build writes promoted Tier A alerts into `state/outbox.ndjson`
- dispatcher sends queued alerts and records `state/sent_alerts.ndjson`

Tailoring is still human-triggered after Sai says YES; it does not happen automatically from score alone.

## V3 direct-source pipeline

V3 is the direct-source layer that tries to convert noisy discovered URLs into a cleaner canonical jobs table.

Run it with:

`python3 scripts/v3_run_cycle.py`

That cycle currently does this:
- seeds prioritized company career boards into discovery
- expands Greenhouse and Lever boards into individual posting URLs via public APIs when available
- expands some Workday and company-hosted careers pages into posting URLs via HTML extraction
- imports newly discovered URLs into `state/v3.sqlite3`
- verifies only probable official posting URLs into `canonical_jobs`
- scores canonical jobs for cyber fit, entry-level fit, and placement quality
- syncs existing application records into the V3 database
- updates the daily goal snapshot

Important V3 rule: company career board homepages are not treated as jobs anymore. They stay in leads as board-only discovery records until expanded into real posting URLs.

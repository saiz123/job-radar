# Smoke Test

## Manual test sequence
```bash
cd /home/saikali/.openclaw/workspace/job-hunter
python3 scripts/hourly_runner.py
python3 scripts/fetch_and_intake.py
python3 scripts/run_pipeline.py
python3 scripts/alert_preview.py
python3 scripts/run_hourly_cycle.py
```

## Check these files after the run
- `state/daily_goal.json`
- `state/fetched_urls.ndjson`
- `state/jobs.ndjson`
- `state/shortlist.ndjson`
- `state/outbox.ndjson`
- `processed/`

## Good signs
- no tracebacks
- daily state updates cleanly
- duplicate jobs do not get appended repeatedly
- alert preview prints the latest strong match if one exists

# Activate Job Hunter Automation

## Goal
Run the job-hunter cycle every hour until 15 appliable jobs are found for the UTC day.

## Single command entrypoint
```bash
cd /home/saikali/.openclaw/workspace/job-hunter
python3 scripts/run_hourly_cycle.py
```

## First smoke test
Run these manually first:
```bash
cd /home/saikali/.openclaw/workspace/job-hunter
python3 scripts/hourly_runner.py
python3 scripts/fetch_and_intake.py
python3 scripts/run_pipeline.py
python3 scripts/alert_preview.py
```

If that looks sane, test the full wrapper:
```bash
python3 scripts/run_hourly_cycle.py
```

## Cron entry
```cron
0 * * * * cd /home/saikali/.openclaw/workspace/job-hunter && /usr/bin/python3 scripts/run_hourly_cycle.py >> /home/saikali/.openclaw/workspace/job-hunter/state/cron.log 2>&1
```

## What it does
- checks if the UTC daily goal is already complete
- exits early if 15 appliable jobs were already found today
- otherwise fetches known direct URLs
- scores and logs jobs
- prepares alert output for strong matches
- updates daily counters

## Important limits
- direct job-board discovery is still partial
- some sites block fetches
- Telegram delivery now depends on a configured OpenClaw Telegram target and reachable gateway/runtime
- tailoring requires a YES-triggered follow-up run

## Daily operating files
- `state/daily_goal.json`
- `state/jobs.ndjson`
- `state/shortlist.ndjson`
- `state/outbox.ndjson`
- `state/sent_alerts.ndjson`
- `state/dispatch_failures.ndjson`
- `state/applications.csv`
- `state/cron.log`

## Delivery commands
Preview unsent alerts without sending:
```bash
python3 scripts/dispatch_outbox.py
```

Actually send unsent alerts to Telegram and mark them sent only on success:
```bash
python3 scripts/dispatch_outbox.py --send --target '<telegram-chat-id-or-@username>'
```

Optional one-shot hourly cycle with dispatch step:
```bash
python3 scripts/run_hourly_cycle.py --dispatch-alerts --dispatch-send --dispatch-target '<telegram-chat-id-or-@username>'
```

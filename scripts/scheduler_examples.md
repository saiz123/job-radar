# Scheduler Examples

## Cron example (hourly)
```cron
0 * * * * cd /home/saikali/.openclaw/workspace/job-hunter && python3 scripts/run_hourly_cycle.py
```

## Shell-wrapper cron example
```cron
0 * * * * cd /home/saikali/.openclaw/workspace/job-hunter && bash scripts/run_hourly_cycle.sh
```

## Why use the wrapper
The wrapper:
1. checks `daily_goal.json`
2. exits early if the daily target is already reached
3. otherwise runs fetch + pipeline in sequence
4. refreshes the counts afterward

## Important
Do not enable unattended cron until runtime command execution is stable and trustworthy.

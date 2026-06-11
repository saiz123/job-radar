# Hourly Cycle Wrapper

## Purpose
Provide one safe entry command for the hourly job-search cycle.

## Command
```bash
python3 scripts/run_hourly_cycle.py
```

or

```bash
bash scripts/run_hourly_cycle.sh
```

## Behavior
- checks daily target state first
- stops immediately if the day is already complete
- otherwise runs fetch + scoring
- refreshes counts afterward
- prints one JSON summary for logging/debugging

## Cron target later
This is the command that should eventually be scheduled hourly.

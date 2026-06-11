# Observability Helpers

## Status report
```bash
python3 scripts/status_report.py
```

Shows:
- daily goal state
- recent incoming files
- recent processed files
- recent jobs ledger entries
- recent shortlist entries
- recent outbox entries

## Find one job across the system
```bash
python3 scripts/find_job.py endo
```

This helps confirm whether a posting made it into:
- incoming
- processed
- state ledgers

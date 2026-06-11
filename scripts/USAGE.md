# Usage

## Manual intake
```bash
python3 scripts/intake.py \
  --title "SOC Analyst I" \
  --company "ExampleCo" \
  --location "Remote - United States" \
  --salary "$70,000-$85,000" \
  --source "LinkedIn" \
  --link "https://example.com/jobs/123" \
  --description "Monitor SIEM alerts, investigate suspicious events, and escalate incidents."
```

## Run the pipeline
```bash
python3 scripts/run_pipeline.py
```

## Preview last alert
```bash
python3 scripts/alert_preview.py
```

## Notes
- This stack is heuristic, not magic.
- It is intentionally conservative on hard reject conditions.
- Add browser-based scraping later only if truly needed.

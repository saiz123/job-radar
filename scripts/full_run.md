# Full Run Sequence

## Recommended order once runtime is healthy
```bash
python3 scripts/fetch_and_intake.py
python3 scripts/run_pipeline.py
python3 scripts/alert_preview.py
```

## If Sai replies YES on a shortlisted job
```bash
python3 scripts/tailor_job.py processed/<job-file>.json
```

## Resulting state
- fetched URLs logged in `state/fetched_urls.ndjson`
- reviewed jobs in `state/jobs.ndjson`
- strong matches in `state/shortlist.ndjson`
- alert payloads in `state/outbox.ndjson`
- tailored packages in `tailored/`
- application tracker rows in `state/applications.csv`

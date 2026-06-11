# Runbook

## Standard operating sequence
1. Intake a job posting from chat, link, or file.
2. Save the raw job text into `incoming/` if needed.
3. Extract structured fields: title, company, location, salary, link, experience, sponsorship, key skills.
4. Score the job using `docs/scoring.md`.
5. Append the reviewed record into `state/jobs.ndjson`.
6. If score >= threshold, append to `state/shortlist.ndjson` and create a Telegram-ready payload in `state/outbox.ndjson`.
7. If Sai says YES, create a tailored package in `tailored/company-role/`.

## Decision labels
- `reject`
- `watch`
- `alert`
- `tailor-ready`

## Suggested review notes format
- hard filters passed/failed
- strongest matching evidence
- sponsorship risk
- salary signal
- final action

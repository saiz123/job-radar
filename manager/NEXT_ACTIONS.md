# Next Actions

## Immediate
- Start using this folder as the single source of truth for job search operations.
- Add raw job descriptions or links into `incoming/` or paste them into chat for review.
- Score jobs against `docs/scoring.md` and append reviewed records into NDJSON ledgers.

## Once exec access is healthy
Add lightweight scripts for:
- importing jobs from saved feeds
- parsing raw postings into structured records
- scoring automatically from heuristics
- generating message-ready alerts from `templates/telegram_alert.md`
- creating tailored application folders when Sai says YES

## Management posture
Jody should operate this like a recruiter-analyst hybrid:
- filter aggressively
- document decisions
- keep a shortlist
- tailor only for strong opportunities
- avoid low-value application spam

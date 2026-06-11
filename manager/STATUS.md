# Job Hunter Status

## Current posture
- Core pipeline exists
- Hourly cron exists
- Tailoring engine exists
- Daily target logic exists
- Sourcing is still partly manual / curated and not fully autonomous

## Reliable today
- ingest direct posting URLs
- ingest pasted/manual job descriptions
- score jobs
- create strong-match alerts for >=85
- create tailored package after YES
- track applications in CSV

## Not fully solved today
- broad autonomous discovery from blocked job boards
- guaranteed 15 quality jobs/day without strong source inputs
- fully hands-off Telegram delivery unless a stable target/chat id is configured and the OpenClaw gateway can execute sends reliably

## Recommendation
Use event-driven alerts + curated sources + manual link drops for highest reliability.

# Automation Notes

## What exists now
- file-first intake format
- heuristic scoring engine
- shortlist and outbox generation
- manual URL/job text intake helper
- alert preview helper

## What still needs runtime support
- scheduled execution
- direct web scraping of search result pages
- Telegram send integration from outbox
- duplicate detection across repeated runs
- smarter parsing for Greenhouse/Lever/Workday variants

## Recommended next phase
Once command execution is stable, add:
1. a scheduler or heartbeat hook that runs `python3 scripts/run_pipeline.py`
2. a fetcher for known friendly job boards
3. dedupe by jobId before appending
4. automatic archive/move for processed intake files

## Caution
Indeed and some major job boards will block generic fetches. Prefer:
- direct Greenhouse / Lever links
- company career pages
- pasted descriptions
- export/search feeds when available

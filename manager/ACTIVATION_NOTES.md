# Activation Notes

## Before enabling cron
- confirm `config/sources.json` contains real direct-posting URLs
- run the smoke test manually
- check that fetched pages are actually parseable
- confirm the daily counter behaves as expected

## After enabling cron
- review `state/cron.log`
- monitor `state/outbox.ndjson`
- keep an eye on false positives and dedupe behavior

## Strategic note
The current system is strongest when fed:
- direct Greenhouse links
- direct Lever links
- company careers postings
- pasted descriptions from job boards that block scraping

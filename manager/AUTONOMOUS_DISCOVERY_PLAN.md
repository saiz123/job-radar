# Autonomous Discovery Plan

## Goal
Search the web every hour without a pre-seeded source list, discover candidate jobs, normalize them, score them, and report results.

## Reality
Modern job boards are hostile to naive scraping. A robust autonomous discovery system needs staged discovery, extraction, dedupe, and reporting.

## Proposed architecture
1. query generator
2. search result collector
3. candidate URL dedupe store
4. scraper/extractor
5. intake normalization
6. scoring pipeline
7. run metrics + reporting

## Discovery strategy
### Stage 1: lightweight discovery
- search engine queries for target roles and companies
- direct career pages when discoverable
- job-board posting URLs surfaced through search results

### Stage 2: hostile-page extraction
- try structured extraction first
- fallback parsing second
- browser-assisted extraction later if worth the operational cost

## Hourly run output
Each run should produce:
- queries attempted
- result URLs found
- new URLs accepted after dedupe
- jobs successfully ingested
- jobs reviewed
- rejects
- strong matches (85+)
- jobs moved to next step
- extraction failures

## Risk notes
- search engines may challenge bots
- some boards require JS/browser automation
- hourly autonomy will need careful dedupe to avoid loops and spam

## Success criteria
- autonomous runs discover new jobs without manual seeding
- at least some fetchable jobs are ingested each day
- strong matches generate alerts
- each run leaves a machine-readable summary

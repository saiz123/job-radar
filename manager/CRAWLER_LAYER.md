# Autonomous Hourly Crawler Layer

## Goal
Find candidate cybersecurity job postings every hour without manual seeding.

## Layer responsibilities
- generate discovery queries
- collect candidate URLs from multiple strategies
- dedupe discovered URLs
- hand URLs to scraper/intake
- trigger scoring pipeline
- record run metrics
- support hourly summaries

## Design rule
The crawler layer should discover. The pipeline should score. The tailoring layer should tailor.
Do not jam all logic into one script.

## Planned modules
- `discover_jobs.py` — query generation and search-based discovery
- `crawl_greenhouse.py` — direct Greenhouse discovery
- `crawl_lever.py` — direct Lever discovery
- `crawl_company_pages.py` — generic careers-page heuristics
- `run_crawler_cycle.py` — orchestrates discovery + scrape + scoring + summary

## Output expectations per run
- candidate URLs found
- new URLs after dedupe
- URLs scraped successfully
- jobs reviewed
- strong matches
- jobs moved to next step
- failures

# Queue Model

## Why
Discovery yield is inconsistent. The crawler should not depend only on same-run fresh links.

## Model
1. discovery appends candidate URLs to `state/crawl_queue.ndjson`
2. scraper processes queued items in batches
3. each queue item should track status such as:
   - pending
   - scraped
   - failed
   - retry
4. hourly runs should process pending backlog before depending on fresh discovery alone

## Benefits
- stable hourly behavior
- retries for temporarily bad links
- better observability of discovery vs scrape failures

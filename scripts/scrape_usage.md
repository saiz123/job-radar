# scrape_job.py

## Purpose
A stronger direct-posting scraper that tries:
- JSON-LD job posting extraction
- Workday-style embedded JSON extraction
- HTML fallback parsing

## Usage
```bash
python3 scripts/scrape_job.py "https://example.com/job-posting"
```

## Output
- writes a normalized markdown intake file into `incoming/`
- prints a small JSON summary to stdout

## Notes
This improves extraction, but will not defeat every anti-bot or JS-heavy flow.
Use it for direct posting URLs, not generic search-result pages.

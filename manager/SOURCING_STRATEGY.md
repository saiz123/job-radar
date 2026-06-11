# Sourcing Strategy

## Reality check
Search-engine scraping is brittle and often blocked. This system should not depend on DuckDuckGo or Indeed SERP scraping as the primary intake path.

## Preferred source hierarchy
1. Direct Greenhouse posting URLs
2. Direct Lever posting URLs
3. Company career pages with stable posting URLs
4. Manual intake pasted from blocked job boards
5. Optional saved searches / export feeds later

## Recommended target-company buckets
- MSSPs
- cloud/security vendors
- consulting firms with security practices
- mid-size SaaS companies with security operations teams
- healthcare/fintech companies with realistic analyst hiring

## Recommended operating model
- keep `config/sources.json` for direct URLs only
- keep `incoming/` for manual job dumps and pasted descriptions
- do not rely on generic SERP scraping for production use

## Human-in-the-loop efficiency
When Sai sends a job link or posting text:
- normalize it into `incoming/`
- score it immediately
- if score >= 85, generate alert
- if Sai says YES, tailor application package

## Next upgrade ideas
- company seed list file
- saved-search intake format
- browser-assisted fetcher only if truly necessary and worth maintenance cost

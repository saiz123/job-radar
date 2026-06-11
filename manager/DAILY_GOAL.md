# Daily Goal Policy

## Goal
Find at least 15 appliable jobs per day.

## Scheduler policy
- check every 1 hour
- if `appliableFound >= 15`, stop searching for the rest of the day
- if fewer than 15 have been found, keep running on the next hourly cycle

## What counts as appliable
A job counts toward the daily target only if:
- it passes hard filters
- it is realistically compatible with Sai's sponsorship situation or at least not explicitly blocked
- it is entry-level / associate or a realistic stretch
- it has a real apply link
- it is not duplicate noise

## Alerting
Only strong matches at score >= 85 should be surfaced as Telegram-style alerts.
A job may count as appliable even if it is not alert-worthy, but alerts should stay selective.

## Tracker
Use `state/daily_goal.json` to track:
- current date
- target
- appliableFound
- lastRunAt
- targetReached

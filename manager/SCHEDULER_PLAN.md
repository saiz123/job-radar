# Scheduler Plan

## Intended cadence
Run the fetch + score pipeline every hour until the daily appliable target is reached.

## Run condition
Before each cycle:
1. read `state/daily_goal.json`
2. if date is stale, reset the counters for the new UTC day
3. if `targetReached` is true, do nothing
4. otherwise run fetch/intake and scoring
5. count new appliable jobs
6. update `appliableFound`
7. if `appliableFound >= 15`, set `targetReached = true`

## Practical note
This is ready to be wired into cron or heartbeat once command execution is stable enough to trust unattended runs.

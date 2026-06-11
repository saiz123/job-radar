# Daily Operations Summary

The system now has a daily target model:
- goal: 15 appliable jobs per UTC day
- cadence: every hour
- stop condition: target reached for the day

## Counts toward target
- `watch`
- `alert`
- `tailor-ready`

provided they pass hard filters and remain realistically appliable.

## Does not count
- hard rejects
- duplicate noise
- jobs without usable apply links

## Alert selectivity
Alerts remain stricter than daily counting.
A role can count toward the daily goal without generating a Telegram alert.
Only score >= 85 should trigger alert creation.

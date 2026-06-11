#!/usr/bin/env python3
"""Print the most recent outbox message for quick review."""

from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "state" / "outbox.ndjson"

if not OUTBOX.exists():
    print("No outbox file yet.")
    raise SystemExit(0)

lines = [line.strip() for line in OUTBOX.read_text(encoding="utf-8").splitlines() if line.strip()]
if not lines:
    print("Outbox is empty.")
    raise SystemExit(0)

payload = json.loads(lines[-1])
print(payload.get("message", ""))

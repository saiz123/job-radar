#!/usr/bin/env python3
"""Summarize the crawl queue by status."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "state" / "crawl_queue.ndjson"

counter = Counter()
if QUEUE.exists():
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('{"_comment"'):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        counter[item.get("status", "unknown")] += 1

print(json.dumps(counter, indent=2))

#!/usr/bin/env python3
"""Find matching job records across incoming, processed, and state files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = [ROOT / "incoming", ROOT / "processed", ROOT / "state"]


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/find_job.py <search-text>")
        raise SystemExit(1)
    needle = sys.argv[1].lower()
    for directory in SEARCH_DIRS:
        for path in sorted(directory.glob("*")):
            if path.is_dir():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if needle in text.lower():
                print(f"===== {path} =====")
                lines = text.splitlines()
                shown = 0
                for idx, line in enumerate(lines, start=1):
                    if needle in line.lower():
                        start = max(1, idx - 2)
                        end = min(len(lines), idx + 2)
                        for i in range(start, end + 1):
                            print(f"{i}: {lines[i-1]}")
                        print()
                        shown += 1
                        if shown >= 3:
                            break


if __name__ == "__main__":
    main()

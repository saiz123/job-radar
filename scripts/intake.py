#!/usr/bin/env python3
"""Helpers for bringing job URLs or pasted job text into the incoming folder.

This is a lightweight companion to run_pipeline.py.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "incoming"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "job"


def now_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--location", default="Unknown")
    parser.add_argument("--salary", default="unknown")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--link", default="")
    parser.add_argument("--description-file", default="")
    parser.add_argument("--description", default="")
    args = parser.parse_args()

    description = args.description
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")

    INCOMING.mkdir(parents=True, exist_ok=True)
    name = f"{now_prefix()}-{slugify(args.company)}-{slugify(args.title)}.md"
    path = INCOMING / name
    body = f"Source: {args.source}\nApply Link: {args.link}\nTitle: {args.title}\nCompany: {args.company}\nLocation: {args.location}\nSalary: {args.salary}\n\n## Description\n{description}\n"
    path.write_text(body, encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()

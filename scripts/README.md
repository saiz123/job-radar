# Scripts

This directory contains the automation layer for the job-hunter system.

Planned flow:
- `intake.py` — ingest URLs and local job files into normalized raw records
- `score.py` — score normalized jobs against Sai's rubric
- `alert.py` — generate Telegram-ready alert payloads
- `run_pipeline.py` — orchestrate intake → score → shortlist → outbox
- `dispatch_outbox.py` — send unsent outbox alerts through OpenClaw and record receipts

These scripts are designed to be file-first and safe to run repeatedly.

#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "state" / "v3.sqlite3"

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_url TEXT NOT NULL UNIQUE,
        company TEXT,
        title TEXT,
        location TEXT,
        snippet TEXT,
        discovered_at TEXT NOT NULL,
        lead_status TEXT NOT NULL DEFAULT 'discovered',
        verification_status TEXT NOT NULL DEFAULT 'pending',
        verification_confidence REAL NOT NULL DEFAULT 0.0,
        canonical_job_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        title TEXT NOT NULL,
        location TEXT,
        official_url TEXT NOT NULL UNIQUE,
        ats_type TEXT,
        requisition_id TEXT,
        description TEXT,
        work_mode TEXT,
        sponsorship_status TEXT DEFAULT 'unknown',
        authorization_risk TEXT DEFAULT 'medium',
        cyber_score INTEGER DEFAULT 0,
        entry_level_score INTEGER DEFAULT 0,
        placement_score INTEGER DEFAULT 0,
        is_open INTEGER DEFAULT 1,
        discovered_from_lead_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_job_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'discovered',
        next_action TEXT,
        next_action_due TEXT,
        notes TEXT,
        tailored_resume_path TEXT,
        cover_letter_path TEXT,
        tailored_at TEXT,
        applied_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        event_type TEXT NOT NULL,
        detail TEXT,
        occurred_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_goal_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT NOT NULL UNIQUE,
        target INTEGER NOT NULL,
        appliable_found INTEGER NOT NULL DEFAULT 0,
        target_reached INTEGER NOT NULL DEFAULT 0,
        last_run_at TEXT
    )
    """,
]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        cur = conn.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(DB_PATH)

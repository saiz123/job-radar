#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
DB_PATH = STATE / "staffing_v4.sqlite3"

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        company TEXT,
        location TEXT,
        source TEXT NOT NULL,
        source_query TEXT,
        url TEXT NOT NULL UNIQUE,
        summary TEXT,
        posted_hint TEXT,
        overall_score INTEGER DEFAULT 0,
        ats_score INTEGER DEFAULT 0,
        experience_score INTEGER DEFAULT 0,
        sponsorship_score INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'discovered',
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resume_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        version_label TEXT NOT NULL,
        resume_path TEXT NOT NULL,
        fit_notes_path TEXT,
        ats_score INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staffing_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'queued',
        channel TEXT NOT NULL DEFAULT 'telegram',
        score INTEGER DEFAULT 0,
        message TEXT,
        confidence_tier TEXT,
        queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
        sent_at TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )
    """,
]


def connect() -> sqlite3.Connection:
    STATE.mkdir(parents=True, exist_ok=True)
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


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def upsert_job(*, title: str, company: str, location: str, source: str, source_query: str, url: str, summary: str, posted_hint: str, overall_score: int, ats_score: int, experience_score: int, sponsorship_score: int, status: str, notes: str) -> None:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO jobs (
                title, company, location, source, source_query, url, summary, posted_hint,
                overall_score, ats_score, experience_score, sponsorship_score, status, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                source = excluded.source,
                source_query = excluded.source_query,
                summary = excluded.summary,
                posted_hint = excluded.posted_hint,
                overall_score = excluded.overall_score,
                ats_score = excluded.ats_score,
                experience_score = excluded.experience_score,
                sponsorship_score = excluded.sponsorship_score,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                title,
                company,
                location,
                source,
                source_query,
                url,
                summary,
                posted_hint,
                overall_score,
                ats_score,
                experience_score,
                sponsorship_score,
                status,
                notes,
                now_iso(),
                now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(DB_PATH)

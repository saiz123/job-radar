from __future__ import annotations

import importlib
import os
from pathlib import Path


def build_env(tmp_path: Path) -> dict[str, str]:
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    return {
        "JOBRADAR_SECRET_KEY": "test-secret-key-32-bytes-minimum-value",
        "JOBRADAR_PASSWORD_HASH": "$argon2id$v=19$m=65536,t=3,p=4$cMOYn1VRSQP+v3AoOVujXg$dp1aIQue6dzvOmFs8v+92bk+bZzFVrjcvCB78plVio8",
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_BIND_HOST": "127.0.0.1",
        "JOBRADAR_BIND_PORT": "8765",
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(processed),
        "JOBRADAR_DISABLE_LOGIN": "false",
        "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "false",
    }


def load_db_module(tmp_path: Path):
    os.environ.update(build_env(tmp_path))
    module = importlib.import_module("jobradar_app.db")
    return importlib.reload(module)


def test_full_up_down_up_cycle_preserves_reversible_migrations(tmp_path: Path) -> None:
    db = load_db_module(tmp_path)

    db.migrate_to_latest()
    assert db.get_schema_version() == 13

    db.downgrade_to_version(0)
    assert db.get_schema_version() == 0

    db.migrate_to_latest()
    assert db.get_schema_version() == 13

    conn = db.connect()
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        user_pref = conn.execute("SELECT id, notification_threshold FROM user_preferences WHERE id = 1").fetchone()
        assert user_pref[0] == 1
        assert user_pref[1] == 85
    finally:
        conn.close()

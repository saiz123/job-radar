from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    secret_key: str
    password_hash: str
    session_dir: Path
    db_path: Path
    import_dir: Path
    careerops_root: Path | None = None
    node_bin: Path | None = None
    cron_dir: Path = Path.home() / ".hermes" / "cron"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    session_cookie: str = "jobradar_session"
    csrf_cookie: str = "jobradar_csrf"
    service_token: str | None = None
    secure_cookies: bool = False
    running_scan_stale_after_s: int = 3600
    disable_login: bool = False
    timezone_name: str = "America/Chicago"
    require_cloudflare_access: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    secret_key = os.environ.get("JOBRADAR_SECRET_KEY", "dev-insecure-secret-key-change-me")
    password_hash = os.environ.get(
        "JOBRADAR_PASSWORD_HASH",
        "$argon2id$v=19$m=65536,t=3,p=4$yJgtrQd7Yh2X2lDqGEd5ew$e3mhkgAbmMi6x4sDwQjM0j9kB2JQ5M0xR0J6NQY8s5M",
    )
    service_token = os.environ.get("JOBRADAR_SERVICE_TOKEN")
    session_dir = Path(os.environ.get("JOBRADAR_SESSION_DIR", "/tmp/jobradar-sessions"))
    db_path = Path(os.environ.get("JOBRADAR_DB_PATH", "/tmp/jobradar.sqlite3"))
    import_dir = Path(os.environ.get("JOBRADAR_IMPORT_DIR", str(Path.cwd() / "processed")))
    careerops_root_raw = os.environ.get("JOBRADAR_CAREEROPS_ROOT")
    node_bin_raw = os.environ.get("JOBRADAR_NODE_BIN")
    cron_dir = Path(os.environ.get("JOBRADAR_CRON_DIR", str(Path.home() / ".hermes" / "cron")))
    bind_host = os.environ.get("JOBRADAR_BIND_HOST", "127.0.0.1")
    bind_port = int(os.environ.get("JOBRADAR_BIND_PORT", "8765"))
    secure_cookies = _env_bool("JOBRADAR_SECURE_COOKIES", default=False)
    running_scan_stale_after_s = int(os.environ.get("JOBRADAR_RUNNING_SCAN_STALE_AFTER_S", "3600"))
    disable_login = _env_bool("JOBRADAR_DISABLE_LOGIN", default=False)
    timezone_name = os.environ.get("JOBRADAR_TIMEZONE", os.environ.get("TZ", "America/Chicago"))
    require_cloudflare_access = _env_bool("JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS", default=False)
    return Settings(
        secret_key=secret_key,
        password_hash=password_hash,
        service_token=service_token,
        session_dir=session_dir,
        db_path=db_path,
        import_dir=import_dir,
        careerops_root=Path(careerops_root_raw) if careerops_root_raw else None,
        node_bin=Path(node_bin_raw) if node_bin_raw else None,
        cron_dir=cron_dir,
        bind_host=bind_host,
        bind_port=bind_port,
        secure_cookies=secure_cookies,
        running_scan_stale_after_s=running_scan_stale_after_s,
        disable_login=disable_login,
        timezone_name=timezone_name,
        require_cloudflare_access=require_cloudflare_access,
    )

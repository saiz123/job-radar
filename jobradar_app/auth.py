from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path

from argon2 import PasswordHasher
from itsdangerous import URLSafeSerializer

from .config import Settings


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    csrf_token: str


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.session_dir.mkdir(parents=True, exist_ok=True)
        self.serializer = URLSafeSerializer(settings.secret_key, salt="jobradar-session")
        self.hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

    def verify_password(self, password: str) -> bool:
        try:
            return self.hasher.verify(self.settings.password_hash, password)
        except Exception:
            return False

    def create_session(self) -> SessionRecord:
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        signed = self.serializer.dumps({"session_id": session_id, "csrf_token": csrf_token})
        self._path(session_id).write_text(signed, encoding="utf-8")
        return SessionRecord(session_id=session_id, csrf_token=csrf_token)

    def exists(self, session_id: str) -> bool:
        return self.read_session(session_id) is not None

    def read_session(self, session_id: str) -> SessionRecord | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            payload = self.serializer.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        stored_session_id = str(payload.get("session_id") or "")
        csrf_token = str(payload.get("csrf_token") or "")
        if stored_session_id != session_id or not csrf_token:
            return None
        return SessionRecord(session_id=stored_session_id, csrf_token=csrf_token)

    def destroy_session(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    def matches_csrf(self, session_id: str, csrf_token: str | None) -> bool:
        if not csrf_token:
            return False
        record = self.read_session(session_id)
        if record is None:
            return False
        return secrets.compare_digest(record.csrf_token, csrf_token)

    def _path(self, session_id: str) -> Path:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return self.settings.session_dir / f"{digest}.session"

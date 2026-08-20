from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


BASE_ENV = {
    "JOBRADAR_SECRET_KEY": "test-secret-key-32-bytes-minimum-value",
    "JOBRADAR_PASSWORD_HASH": "$argon2id$v=19$m=65536,t=3,p=4$cMOYn1VRSQP+v3AoOVujXg$dp1aIQue6dzvOmFs8v+92bk+bZzFVrjcvCB78plVio8",
    "JOBRADAR_SERVICE_TOKEN": "service-token-test-value",
    "JOBRADAR_BIND_HOST": "127.0.0.1",
    "JOBRADAR_BIND_PORT": "8765",
    "JOBRADAR_SECURE_COOKIES": "false",
    "JOBRADAR_RUNNING_SCAN_STALE_AFTER_S": "3600",
    "JOBRADAR_DISABLE_LOGIN": "false",
    "JOBRADAR_TIMEZONE": "America/Chicago",
    "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "false",
}


def build_client(tmp_path: Path, extra_env: dict[str, str] | None = None) -> TestClient:
    env = {
        **BASE_ENV,
        "JOBRADAR_SESSION_DIR": str(tmp_path / "sessions"),
        "JOBRADAR_DB_PATH": str(tmp_path / "jobradar.sqlite3"),
        "JOBRADAR_IMPORT_DIR": str(tmp_path / "processed"),
    }
    if extra_env:
        env.update(extra_env)
    Path(env["JOBRADAR_IMPORT_DIR"]).mkdir(parents=True, exist_ok=True)
    os.environ.update(env)
    module = importlib.import_module("jobradar_app.main")
    module = importlib.reload(module)
    return TestClient(module.create_app())


def test_healthz_is_public(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_readyz_is_public(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_root_redirects_to_login_when_anonymous(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_jobs_redirects_to_login_when_anonymous(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/jobs", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_api_requires_authentication(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/v1/jobs")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_api_accepts_service_token_authentication(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get(
        "/api/v1/jobs",
        headers={
            "Authorization": "Bearer service-token-test-value",
            "X-JobRadar-Actor": "hermes",
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_disable_login_allows_browser_and_api_testing_without_session(tmp_path: Path) -> None:
    client = build_client(tmp_path, extra_env={"JOBRADAR_DISABLE_LOGIN": "true"})

    page = client.get("/", follow_redirects=False)
    assert page.status_code == 200
    assert "Job Radar" in page.text

    api = client.get("/api/v1/jobs")
    assert api.status_code == 200
    assert api.json()["total"] == 0

    created = client.post(
        "/api/v1/companies",
        json={"name": "Agent Test Co", "domain": "agent-test.example"},
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Agent Test Co"


def test_login_form_sets_session_and_grants_access(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.post(
        "/auth/login",
        data={"password": "changeme-test-password"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "jobradar_session" in response.cookies
    session_cookie = response.cookies.get("jobradar_session")
    csrf_cookie = response.cookies.get("jobradar_csrf")
    assert session_cookie is not None and session_cookie != ""
    assert csrf_cookie is not None and csrf_cookie != ""
    cookie_headers = response.headers.get_list("set-cookie")
    session_header = next(value for value in cookie_headers if value.startswith("jobradar_session="))
    csrf_header = next(value for value in cookie_headers if value.startswith("jobradar_csrf="))
    assert "HttpOnly" in session_header
    assert "SameSite=lax" in session_header
    assert "HttpOnly" not in csrf_header
    assert "SameSite=lax" in csrf_header

    protected = client.get("/")
    assert protected.status_code == 200
    assert "Job Radar" in protected.text


def test_secure_cookies_enable_when_configured(tmp_path: Path) -> None:
    client = build_client(tmp_path, extra_env={"JOBRADAR_SECURE_COOKIES": "true"})

    response = client.post(
        "/auth/login",
        data={"password": "changeme-test-password"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    cookie_headers = response.headers.get_list("set-cookie")
    assert any(header.startswith("jobradar_session=") and "Secure" in header for header in cookie_headers)
    assert any(header.startswith("jobradar_csrf=") and "Secure" in header for header in cookie_headers)


def test_logout_clears_session_and_blocks_followup_access(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    login = client.post("/auth/login", data={"password": "changeme-test-password"}, follow_redirects=False)
    assert login.status_code == 302

    logout = client.post("/auth/logout", follow_redirects=False)

    assert logout.status_code == 302
    assert logout.headers["location"] == "/login"
    cookie_headers = logout.headers.get_list("set-cookie")
    assert any(header.startswith("jobradar_session=") and "Max-Age=0" in header for header in cookie_headers)
    assert any(header.startswith("jobradar_csrf=") and "Max-Age=0" in header for header in cookie_headers)

    protected = client.get("/", follow_redirects=False)
    assert protected.status_code == 302
    assert protected.headers["location"] == "/login"


def test_login_rejects_bad_password(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.post("/auth/login", data={"password": "wrong"})

    assert response.status_code == 401
    assert "Invalid password" in response.text


def test_login_page_has_security_headers(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/login")

    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_robots_txt_disallows_all(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"


def test_cloudflare_access_gate_blocks_mutating_requests_without_headers(tmp_path: Path) -> None:
    client = build_client(tmp_path, extra_env={"JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "true"})

    response = client.post(
        "/api/v1/companies",
        json={"name": "Blocked Co", "domain": "blocked.example"},
        headers={
            "Authorization": "Bearer service-token-test-value",
            "X-JobRadar-Actor": "hermes",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "cloudflare_access_required"


def test_cloudflare_access_gate_allows_mutations_with_cf_headers(tmp_path: Path) -> None:
    client = build_client(tmp_path, extra_env={"JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "true"})

    response = client.post(
        "/api/v1/companies",
        json={"name": "Allowed Co", "domain": "allowed.example"},
        headers={
            "Authorization": "Bearer service-token-test-value",
            "X-JobRadar-Actor": "hermes",
            "CF-Access-Authenticated-User-Email": "sai@example.com",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Allowed Co"


def test_disable_login_bypasses_optional_cloudflare_gate_for_agent_testing(tmp_path: Path) -> None:
    client = build_client(
        tmp_path,
        extra_env={
            "JOBRADAR_DISABLE_LOGIN": "true",
            "JOBRADAR_REQUIRE_CLOUDFLARE_ACCESS": "true",
        },
    )

    response = client.post(
        "/api/v1/companies",
        json={"name": "Agent Mode Co", "domain": "agent-mode.example"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Agent Mode Co"

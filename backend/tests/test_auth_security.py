from unittest.mock import MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
import pytest

from backend.app import rate_limiter
from backend.app.main import app
from backend.app.auth import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, SESSION_COOKIE, get_current_user
from backend.app.rate_limiter import _MEMORY_RATE_LIMITS

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_memory_rate_limiter(monkeypatch):
    _MEMORY_RATE_LIMITS.clear()

    def fail_redis(*args, **kwargs):
        raise RuntimeError("redis disabled for auth tests")

    monkeypatch.setattr(rate_limiter.Redis, "from_url", fail_redis)
    yield
    _MEMORY_RATE_LIMITS.clear()


def test_login_sets_httponly_cookies_and_no_tokens_in_body() -> None:
    mock_supabase_response = {
        "access_token": "fake-access-token-123",
        "refresh_token": "fake-refresh-token-456",
        "expires_in": 3600,
        "user": {
            "id": str(uuid4()),
            "email": "user@example.com",
        },
    }

    with patch("backend.app.api.auth_session._supabase_password_login", return_value=mock_supabase_response):
        response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password123!"})

    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert "user" in data
    assert data["user"]["email"] == "user@example.com"

    # Verify access_token and refresh_token are NOT returned in response body
    assert "access_token" not in data
    assert "refresh_token" not in data

    # Verify HttpOnly cookies are set
    cookies = response.cookies
    assert ACCESS_TOKEN_COOKIE in cookies
    assert REFRESH_TOKEN_COOKIE in cookies
    assert SESSION_COOKIE in cookies


def test_me_endpoint_unauthenticated_returns_401() -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "Authentication required" in response.json().get("detail", "")


def test_me_endpoint_authenticated_returns_profile() -> None:
    user_id = str(uuid4())
    mock_user_dict = {
        "id": user_id,
        "email": "employee@example.com",
        "role": "employee",
        "tenant_id": user_id,
        "status": "Active",
    }

    app.dependency_overrides[get_current_user] = lambda: mock_user_dict
    try:
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user_id
        assert data["email"] == "employee@example.com"
        assert data["role"] == "employee"
        assert data["status"] == "Active"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_authorization_restriction() -> None:
    user_id = str(uuid4())
    employee_user = {
        "id": user_id,
        "email": "employee@example.com",
        "role": "employee",
        "tenant_id": user_id,
        "status": "Active",
    }

    app.dependency_overrides[get_current_user] = lambda: employee_user
    try:
        response = client.get("/api/admin/employees")
        assert response.status_code == 403
        assert "Administrator privileges required" in response.json().get("detail", "")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_superadmin_authorization_restriction() -> None:
    user_id = str(uuid4())
    admin_user = {
        "id": user_id,
        "email": "admin@example.com",
        "role": "admin",
        "tenant_id": user_id,
        "status": "Active",
    }

    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        response = client.get("/api/superadmin/workspaces")
        assert response.status_code == 403
        assert "Superadmin privileges required" in response.json().get("detail", "")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_logout_clears_cookies() -> None:
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Verify cookies in Set-Cookie header have deletion/expiration directives
    set_cookie_header = response.headers.get("set-cookie", "")
    assert ACCESS_TOKEN_COOKIE in set_cookie_header or SESSION_COOKIE in set_cookie_header


def test_login_rate_limit_blocks_repeated_failed_attempts() -> None:
    _MEMORY_RATE_LIMITS.clear()

    def fail_login(email: str, password: str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    with patch("backend.app.api.auth_session._supabase_password_login", side_effect=fail_login):
        for _ in range(5):
            response = client.post("/api/auth/login", json={"email": "target@example.com", "password": "WrongPass1!"})
            assert response.status_code == 401

        blocked = client.post("/api/auth/login", json={"email": "target@example.com", "password": "WrongPass1!"})
        assert blocked.status_code == 429
        assert blocked.headers.get("retry-after")


def test_login_rate_limit_window_allows_later_legitimate_login() -> None:
    from backend.app import rate_limiter

    _MEMORY_RATE_LIMITS.clear()
    clock = {"now": 1000.0}

    def fake_time():
        return clock["now"]

    def fail_login(email: str, password: str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    success = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 3600,
        "user": {"id": str(uuid4()), "email": "target@example.com"},
    }

    with patch.object(rate_limiter.time, "time", side_effect=fake_time):
        with patch("backend.app.api.auth_session._supabase_password_login", side_effect=fail_login):
            for _ in range(5):
                response = client.post("/api/auth/login", json={"email": "target@example.com", "password": "WrongPass1!"})
                assert response.status_code == 401
            assert client.post("/api/auth/login", json={"email": "target@example.com", "password": "WrongPass1!"}).status_code == 429

        clock["now"] += 901
        with patch("backend.app.api.auth_session._supabase_password_login", return_value=success):
            response = client.post("/api/auth/login", json={"email": "target@example.com", "password": "CorrectPass1!"})
            assert response.status_code == 200


def test_email_login_limit_does_not_lock_different_account() -> None:
    _MEMORY_RATE_LIMITS.clear()

    def auth_side_effect(email: str, password: str):
        if email == "other@example.com":
            return {
                "access_token": "other-access",
                "refresh_token": "other-refresh",
                "expires_in": 3600,
                "user": {"id": str(uuid4()), "email": email},
            }
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    with patch("backend.app.api.auth_session._supabase_password_login", side_effect=auth_side_effect):
        for _ in range(5):
            response = client.post("/api/auth/login", json={"email": "target@example.com", "password": "WrongPass1!"})
            assert response.status_code == 401

        response = client.post("/api/auth/login", json={"email": "other@example.com", "password": "CorrectPass1!"})
        assert response.status_code == 200


def test_login_ip_limit_ignores_spoofed_forwarded_headers() -> None:
    _MEMORY_RATE_LIMITS.clear()

    def fail_login(email: str, password: str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    with patch("backend.app.api.auth_session._supabase_password_login", side_effect=fail_login):
        for index in range(10):
            response = client.post(
                "/api/auth/login",
                json={"email": f"user-{index}@example.com", "password": "WrongPass1!"},
                headers={"X-Forwarded-For": f"203.0.113.{index}"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/auth/login",
            json={"email": "another@example.com", "password": "WrongPass1!"},
            headers={"X-Forwarded-For": "198.51.100.77"},
        )
        assert blocked.status_code == 429


def test_change_password_requires_correct_current_password() -> None:
    user_id = str(uuid4())
    user = {
        "id": user_id,
        "email": "employee@example.com",
        "role": "employee",
        "tenant_id": user_id,
        "status": "Active",
    }

    def fail_current_password(email: str, password: str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    supabase = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with patch("backend.app.api.auth_session._supabase_password_login", side_effect=fail_current_password):
            with patch("backend.app.api.auth_session.get_supabase", return_value=supabase):
                response = client.post(
                    "/api/auth/change-password",
                    json={"current_password": "WrongPass1!", "password": "NewPassword123!"},
                    cookies={ACCESS_TOKEN_COOKIE: "current-access"},
                )
        assert response.status_code == 401
        supabase.auth.admin.update_user_by_id.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_successful_change_password_invalidates_other_sessions() -> None:
    user_id = str(uuid4())
    user = {
        "id": user_id,
        "email": "employee@example.com",
        "role": "employee",
        "tenant_id": user_id,
        "status": "Active",
    }
    supabase = MagicMock()
    verification_session = {"access_token": "verification-access"}
    logout_calls = []

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with patch("backend.app.api.auth_session._supabase_password_login", return_value=verification_session):
            with patch("backend.app.api.auth_session.get_supabase", return_value=supabase):
                with patch("backend.app.api.auth_session._logout_session_token", side_effect=lambda token, scope: logout_calls.append((token, scope))):
                    response = client.post(
                        "/api/auth/change-password",
                        json={"current_password": "CurrentPass123!", "password": "NewPassword123!"},
                        cookies={ACCESS_TOKEN_COOKIE: "current-access"},
                    )

        assert response.status_code == 200
        supabase.auth.admin.update_user_by_id.assert_called_once_with(user_id, {"password": "NewPassword123!"})
        assert ("verification-access", "local") in logout_calls
        assert ("current-access", "others") in logout_calls
    finally:
        app.dependency_overrides.pop(get_current_user, None)

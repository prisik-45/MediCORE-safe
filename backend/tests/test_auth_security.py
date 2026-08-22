from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.auth import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, SESSION_COOKIE, get_current_user

client = TestClient(app)


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

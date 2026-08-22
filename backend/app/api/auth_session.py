import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.auth import (
    REFRESH_TOKEN_COOKIE,
    clear_session_cookies,
    get_current_user,
    set_session_cookies,
)
from backend.app.config import get_settings
from backend.app.db import get_supabase
from backend.app.rate_limiter import (
    check_rate_limit,
    get_client_ip,
    rate_limit_retry_after,
    reset_rate_limit,
)
from backend.app.schemas import validate_password_strength

router = APIRouter()
logger = logging.getLogger(__name__)

LOGIN_IP_LIMIT = 10
LOGIN_IP_WINDOW_SECONDS = 5 * 60
LOGIN_EMAIL_LIMIT = 5
LOGIN_EMAIL_WINDOW_SECONDS = 15 * 60
LOGIN_IP_SCOPE = "auth_login_ip"
LOGIN_EMAIL_SCOPE = "auth_login_email"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    password: str

    @field_validator("password")
    @classmethod
    def validate_pwd(cls, value: str) -> str:
        return validate_password_strength(value)


def _supabase_password_login(email: str, password: str) -> dict[str, Any]:
    settings = get_settings()
    base_url = str(settings.supabase_url).rstrip("/") + "/"
    endpoint = urljoin(base_url, "auth/v1/token?grant_type=password")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(endpoint, headers=headers, json={"email": email, "password": password})
    except httpx.HTTPError as exc:
        logger.warning("Supabase password login request failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service is unavailable.") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    data = response.json()
    if not data.get("access_token"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return data


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    email = payload.email.strip().lower()
    _ensure_login_allowed(request, email)
    try:
        data = _supabase_password_login(email, payload.password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            _record_login_failure(request, email)
        raise
    reset_rate_limit(email, LOGIN_EMAIL_SCOPE)
    set_session_cookies(
        response,
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_in=data.get("expires_in"),
    )
    user = data.get("user") or {}
    return {
        "success": True,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
        },
    }


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return authenticated current user profile."""
    return {
        "id": current_user["id"],
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "tenant_id": current_user.get("tenant_id"),
        "status": current_user.get("status"),
    }


@router.get("/session")
def session(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return get_me(current_user)


@router.post("/refresh")
def refresh(request: Request, response: Response) -> dict[str, Any]:
    """Refresh session using refresh token stored in HttpOnly cookie."""
    refresh_token = (
        request.cookies.get(REFRESH_TOKEN_COOKIE)
        or request.cookies.get("sb-refresh-token")
        or ""
    )
    if not refresh_token:
        clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing or expired.",
        )

    supabase = get_supabase()
    try:
        res = supabase.auth.refresh_session(refresh_token)
        if not res or not res.session or not res.session.access_token:
            clear_session_cookies(response)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to refresh session.",
            )
        set_session_cookies(
            response,
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            expires_in=res.session.expires_in,
        )
        return {"success": True}
    except Exception as exc:
        logger.warning("Session refresh failed: %s", exc)
        clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session refresh failed.",
        ) from exc


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookies(response)
    return {"success": True}


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    email = str(current_user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current user email is unavailable.")

    try:
        verification_session = _supabase_password_login(email, payload.current_password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect.") from exc
        raise

    verification_token = clean_optional_token(verification_session.get("access_token"))
    if verification_token:
        _logout_session_token(verification_token, scope="local")

    try:
        get_supabase().auth.admin.update_user_by_id(
            str(current_user["id"]),
            {"password": payload.password},
        )
    except Exception as exc:
        logger.warning("Password change failed for user_id=%s: %s", current_user.get("id"), exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update password.") from exc
    current_access_token = _current_access_token(request)
    if current_access_token:
        _logout_session_token(current_access_token, scope="others")
    else:
        logger.warning("Password changed for user_id=%s but current session token was unavailable for other-session revocation", current_user.get("id"))
    return {"success": True}


def _raise_login_rate_limited(retry_after: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many login attempts. Please try again in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


def _ensure_login_allowed(request: Request, email: str) -> None:
    ip_retry_after = rate_limit_retry_after(
        key=get_client_ip(request),
        max_requests=LOGIN_IP_LIMIT,
        window_seconds=LOGIN_IP_WINDOW_SECONDS,
        scope=LOGIN_IP_SCOPE,
    )
    email_retry_after = rate_limit_retry_after(
        key=email,
        max_requests=LOGIN_EMAIL_LIMIT,
        window_seconds=LOGIN_EMAIL_WINDOW_SECONDS,
        scope=LOGIN_EMAIL_SCOPE,
    )
    retry_after = max(ip_retry_after, email_retry_after)
    if retry_after > 0:
        _raise_login_rate_limited(retry_after)


def _record_login_failure(request: Request, email: str) -> None:
    ip_allowed, ip_retry_after = check_rate_limit(
        key=get_client_ip(request),
        max_requests=LOGIN_IP_LIMIT,
        window_seconds=LOGIN_IP_WINDOW_SECONDS,
        scope=LOGIN_IP_SCOPE,
    )
    email_allowed, email_retry_after = check_rate_limit(
        key=email,
        max_requests=LOGIN_EMAIL_LIMIT,
        window_seconds=LOGIN_EMAIL_WINDOW_SECONDS,
        scope=LOGIN_EMAIL_SCOPE,
    )
    if not ip_allowed or not email_allowed:
        _raise_login_rate_limited(max(ip_retry_after, email_retry_after))


def clean_optional_token(value: object) -> str:
    return str(value or "").strip()


def _current_access_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token.lower() not in {"undefined", "null"}:
            return token
    return clean_optional_token(
        request.cookies.get("medicore_access_token")
        or request.cookies.get("medicore_session_id")
        or request.cookies.get("sb-access-token")
    )


def _logout_session_token(access_token: str, scope: str) -> None:
    settings = get_settings()
    endpoint = urljoin(str(settings.supabase_url).rstrip("/") + "/", f"auth/v1/logout?scope={scope}")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {access_token}",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(endpoint, headers=headers)
        if response.status_code >= 400:
            logger.warning("Supabase logout scope=%s failed with status=%s", scope, response.status_code)
    except httpx.HTTPError as exc:
        logger.warning("Supabase logout scope=%s request failed: %s", scope, exc)

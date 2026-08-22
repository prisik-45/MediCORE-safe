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
from backend.app.schemas import validate_password_strength

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
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
def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    data = _supabase_password_login(payload.email.strip(), payload.password)
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
def change_password(payload: PasswordChangeRequest, current_user: dict = Depends(get_current_user)) -> dict[str, bool]:
    try:
        get_supabase().auth.admin.update_user_by_id(
            str(current_user["id"]),
            {"password": payload.password},
        )
    except Exception as exc:
        logger.warning("Password change failed for user_id=%s: %s", current_user.get("id"), exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update password.") from exc
    return {"success": True}

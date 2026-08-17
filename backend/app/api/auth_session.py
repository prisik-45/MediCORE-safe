import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.auth import SESSION_COOKIE, delete_auth_session, get_current_user, store_auth_session
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


def _cookie_secure() -> bool:
    settings = get_settings()
    return settings.environment.lower() == "production" or settings.frontend_origin.startswith("https://")


def _cookie_samesite() -> str:
    settings = get_settings()
    if not _cookie_secure():
        return "lax"
    frontend_host = urlparse(settings.frontend_origin).hostname
    api_host = urlparse(settings.api_base_url).hostname
    if frontend_host and api_host and frontend_host != api_host:
        return "none"
    return "lax"


def _set_session_cookies(response: Response, access_token: str, refresh_token: str | None, expires_in: int | None) -> None:
    session_id, max_age = store_auth_session(access_token, refresh_token, expires_in)
    secure = _cookie_secure()
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=_cookie_samesite(),
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    secure = _cookie_secure()
    samesite = _cookie_samesite()
    for cookie_name in (SESSION_COOKIE, "medicore_access_token", "medicore_refresh_token", "sb-access-token"):
        response.delete_cookie(cookie_name, path="/", secure=secure, samesite=samesite)


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
    _set_session_cookies(
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


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    delete_auth_session(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookies(response)
    return {"success": True}


@router.get("/session")
def session(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "id": current_user["id"],
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "tenant_id": current_user.get("tenant_id"),
        "status": current_user.get("status"),
    }


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

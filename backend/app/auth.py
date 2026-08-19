import base64
import hashlib
import logging
from urllib.parse import urlparse
from uuid import UUID
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import get_settings
from backend.app.db import get_supabase, get_db
from backend.app.models import Profile

settings = get_settings()
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

SESSION_COOKIE = "medicore_session_id"
ACCESS_TOKEN_COOKIE = "medicore_access_token"
REFRESH_TOKEN_COOKIE = "medicore_refresh_token"


def data_tenant_id_for_user(user_id: UUID, profile: Profile | None = None) -> UUID:
    """Return the private catalogue-data namespace for a signed-in account."""
    return user_id


def supabase_url_summary() -> str:
    return urlparse(str(settings.supabase_url).strip()).netloc or "<invalid-supabase-url>"


def get_fernet() -> Fernet:
    """Return Fernet instance using MAILBOX_FERNET_KEY."""
    if settings.mailbox_fernet_key and settings.mailbox_fernet_key.strip():
        raw = settings.mailbox_fernet_key.strip()
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            hashed = hashlib.sha256(raw.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(hashed))

    raise RuntimeError("MAILBOX_FERNET_KEY is required for mailbox password encryption.")


def encrypt_password(password: str) -> str:
    """Symmetrically encrypt an email/IMAP password."""
    f = get_fernet()
    return f.encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_password(encrypted_password: str) -> str:
    """Symmetrically decrypt an email/IMAP password with dual-read fallback."""
    try:
        f = get_fernet()
        return f.decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
    except Exception as primary_err:
        if settings.mailbox_fernet_key:
            try:
                legacy_material = settings.supabase_service_role_key.encode("utf-8")
                hashed = hashlib.sha256(legacy_material).digest()
                legacy_fernet = Fernet(base64.urlsafe_b64encode(hashed))
                return legacy_fernet.decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
            except Exception:
                pass
        raise primary_err


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """Validate the Supabase JWT from an HttpOnly cookie or bearer header."""
    header_token = credentials.credentials.strip() if credentials and credentials.credentials else ""
    token = "" if header_token.lower() in {"undefined", "null"} else header_token

    if not token:
        token = (
            request.cookies.get(ACCESS_TOKEN_COOKIE)
            or request.cookies.get(SESSION_COOKIE)
            or request.cookies.get("sb-access-token")
            or ""
        )

    refresh_token = (
        request.cookies.get(REFRESH_TOKEN_COOKIE)
        or request.cookies.get("sb-refresh-token")
        or ""
    )

    supabase: Client = get_supabase()
    user_response = None

    if token:
        try:
            user_response = supabase.auth.get_user(token)
        except Exception:
            logger.warning("Supabase token verification failed for access token")

    # If access token is invalid/missing but refresh token exists, attempt refresh
    if (not user_response or not getattr(user_response, "user", None)) and refresh_token:
        try:
            refresh_res = supabase.auth.refresh_session(refresh_token)
            if refresh_res and refresh_res.user:
                user_response = refresh_res
        except Exception as e:
            logger.warning("Supabase session refresh failed: %s", e)

    if not user_response or not getattr(user_response, "user", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = user_response.user
    user_uuid = UUID(user.id)

    try:
        profile = db.query(Profile).filter(Profile.id == user_uuid).first()
    except SQLAlchemyError:
        logger.exception("Database profile lookup failed for authenticated user %s", user_uuid)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed while loading user profile.",
        )

    custom_role = "employee"
    tenant_id = str(data_tenant_id_for_user(user_uuid))
    status_str = "Active"

    if profile:
        custom_role = profile.role or "employee"
        tenant_id = str(data_tenant_id_for_user(user_uuid, profile))
        status_str = profile.status or "Active"

        if custom_role == "employee" and profile.tenant_id:
            try:
                admin_profile = db.query(Profile).filter(Profile.id == profile.tenant_id).first()
            except SQLAlchemyError:
                logger.exception("Database admin profile lookup failed for tenant %s", profile.tenant_id)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database connection failed while loading tenant profile.",
                )
            if admin_profile and admin_profile.status == "Disabled":
                status_str = "Disabled"
    else:
        logger.warning("Authenticated user %s has no server-side profile", user_uuid)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorised to use MediCORE",
        )

    if status_str in ("Disabled", "Pending Approval"):
        detail_msg = "You are not authorised to use MediCORE"
        if status_str == "Pending Approval":
            detail_msg = "Your workspace registration is pending approval by the MediCORE Superadmin."
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail_msg,
        )

    return {
        "id": user.id,
        "email": user.email,
        "role": custom_role,
        "tenant_id": tenant_id,
        "status": status_str,
    }


def get_current_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Enforce admin authorization rules."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Administrator privileges required.",
        )
    return current_user


def get_current_superadmin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Enforce superadmin authorization rules."""
    if current_user.get("role") != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Superadmin privileges required.",
        )
    return current_user

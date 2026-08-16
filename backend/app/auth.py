import base64
import hashlib
import logging
from urllib.parse import urlparse
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import get_settings
from backend.app.db import get_supabase, get_db
from backend.app.models import Profile

settings = get_settings()
security = HTTPBearer()
logger = logging.getLogger(__name__)


def data_tenant_id_for_user(user_id: UUID, profile: Profile | None = None) -> UUID:
    """Return the private catalogue-data namespace for a signed-in account.

    ``profiles.tenant_id`` is an organisation/invitation relationship used by
    the admin portal. It is not a data-sharing boundary for employee inboxes.
    """
    return user_id


def supabase_url_summary() -> str:
    return urlparse(str(settings.supabase_url).strip()).netloc or "<invalid-supabase-url>"

def get_fernet() -> Fernet:
    """Return Fernet instance using MAILBOX_FERNET_KEY or legacy derived key."""
    if settings.mailbox_fernet_key and settings.mailbox_fernet_key.strip():
        raw = settings.mailbox_fernet_key.strip()
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            hashed = hashlib.sha256(raw.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(hashed))

    # Backward compatibility fallback
    key_material = settings.supabase_service_role_key.encode("utf-8")
    hashed = hashlib.sha256(key_material).digest()
    fernet_key = base64.urlsafe_b64encode(hashed)
    return Fernet(fernet_key)

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
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> dict:
    """FastAPI dependency to extract, validate the Supabase bearer JWT, and load the DB Profile details."""
    token = credentials.credentials
    supabase: Client = get_supabase()
    try:
        response = supabase.auth.get_user(token)
    except Exception:
        logger.exception(
            "Supabase token verification request failed against host %s",
            supabase_url_summary(),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication service could not be reached.",
        )

    try:
        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
            )
        
        # Load user profile for custom role, status and tenant_id
        user_uuid = UUID(response.user.id)
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
            
            # Check the associated admin's status
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
                detail="You are not authorised to use MediCORE"
            )
            
        if status_str in ("Disabled", "Pending Approval"):
            detail_msg = "You are not authorised to use MediCORE"
            if status_str == "Pending Approval":
                detail_msg = "Your workspace registration is pending approval by the MediCORE Superadmin."
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail_msg
            )
            
        return {
            "id": response.user.id,
            "email": response.user.email,
            "role": custom_role, # Use custom profile role (e.g. admin or employee)
            "tenant_id": tenant_id,
            "status": status_str,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed. Invalid token.",
        )

def get_current_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Enforce admin authorization rules."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Administrator privileges required."
        )
    return current_user

def get_current_superadmin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Enforce superadmin authorization rules."""
    if current_user.get("role") != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Superadmin privileges required."
        )
    return current_user


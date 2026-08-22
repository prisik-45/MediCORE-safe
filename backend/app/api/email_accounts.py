import imaplib
import logging
import json
from urllib.parse import unquote, urlparse
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.config import get_settings
from backend.app.db import get_db, get_supabase
from backend.app.auth import get_current_user, encrypt_password
from backend.app.models import CatalogEmail, CatalogItem, EmailAccount, EmailFilter, EmailSyncSetting, Supplier
from backend.app.schemas import clean_optional_text
from backend.app.security import validate_public_network_host
from backend.app.services.email_ingestion import filter_trusted_pending_approvals

router = APIRouter()
logger = logging.getLogger(__name__)


def _storage_object_path_from_public_url(url: str | None) -> str | None:
    if not url:
        return None
    marker = "/storage/v1/object/public/"
    parsed_path = urlparse(url).path
    if marker not in parsed_path:
        return None
    bucket_and_path = parsed_path.split(marker, 1)[1]
    bucket_prefix = f"{get_settings().supabase_storage_bucket}/"
    if not bucket_and_path.startswith(bucket_prefix):
        return None
    return unquote(bucket_and_path[len(bucket_prefix):])


def _certificate_storage_paths(raw_payload: dict | None) -> list[str]:
    values = (raw_payload or {}).get("certificate_pdfs")
    if not isinstance(values, list):
        return []
    return [
        path
        for row in values
        if isinstance(row, dict)
        for path in [clean_optional_text(row.get("storage_path"))]
        if path
    ]


def _delete_storage_objects(object_paths: list[str]) -> None:
    paths = list(dict.fromkeys(path for path in object_paths if path))
    if not paths:
        return
    try:
        get_supabase().storage.from_(get_settings().supabase_storage_bucket).remove(paths)
    except Exception:
        logger.warning("Failed to delete mailbox storage objects during disconnect purge", exc_info=True)


def _pending_approval_belongs_to_account(item: dict, account_id: UUID) -> bool:
    email_id = clean_optional_text(item.get("email_id"))
    return bool(email_id and email_id.startswith(f"{account_id}:"))


def _purge_mailbox_ingested_data(db: Session, account: EmailAccount) -> list[str]:
    account_prefix = f"{account.id}:"
    emails = (
        db.query(CatalogEmail)
        .filter(CatalogEmail.tenant_id == account.user_id)
        .filter(CatalogEmail.raw_email_id.like(f"{account_prefix}%"))
        .all()
    )
    email_ids = [email.id for email in emails]
    supplier_ids = {email.supplier_id for email in emails}
    storage_paths: list[str] = []

    if email_ids:
        items = db.query(CatalogItem).filter(CatalogItem.catalog_email_id.in_(email_ids)).all()
        for item in items:
            storage_paths.extend(_certificate_storage_paths(item.raw_payload))
        db.query(CatalogItem).filter(CatalogItem.catalog_email_id.in_(email_ids)).delete(synchronize_session=False)

    for email in emails:
        storage_paths.extend(_certificate_storage_paths(getattr(email, "raw_payload", None)))
        path = _storage_object_path_from_public_url(email.pdf_url)
        if path:
            storage_paths.append(path)
        db.delete(email)

    sync_setting = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == account.user_id).first()
    if sync_setting and sync_setting.pending_approvals:
        try:
            pending_items = json.loads(sync_setting.pending_approvals or "[]")
        except Exception:
            pending_items = []
        if isinstance(pending_items, list):
            kept_items = [
                item
                for item in pending_items
                if not (isinstance(item, dict) and _pending_approval_belongs_to_account(item, account.id))
            ]
            sync_setting.pending_approvals = json.dumps(kept_items)

    db.flush()
    for supplier_id in supplier_ids:
        has_emails = db.query(CatalogEmail.id).filter(CatalogEmail.supplier_id == supplier_id).first()
        has_items = db.query(CatalogItem.id).filter(CatalogItem.supplier_id == supplier_id).first()
        if not has_emails and not has_items:
            supplier = (
                db.query(Supplier)
                .filter(Supplier.id == supplier_id)
                .filter(Supplier.tenant_id == account.user_id)
                .first()
            )
            if supplier:
                db.delete(supplier)

    return storage_paths

# --- Pydantic Schemas ---

class IMAPTestRequest(BaseModel):
    provider: str = Field(..., description="E.g., Gmail, Outlook, Custom")
    email_address: EmailStr = Field(..., description="The full email address")
    imap_host: str = Field(..., description="IMAP server host")
    imap_port: int = Field(993, ge=1, le=65535, description="IMAP SSL port")
    password: str = Field(..., min_length=1, description="Email password or App-specific password")

    @field_validator("imap_host")
    @classmethod
    def validate_imap_host(cls, value: str) -> str:
        return validate_public_network_host(value, field_name="imap_host")

    @field_validator("imap_port")
    @classmethod
    def validate_imap_port(cls, value: int) -> int:
        if value != 993:
            raise ValueError("Only IMAP over SSL on port 993 is supported.")
        return value

class IMAPTestResponse(BaseModel):
    success: bool
    message: str

class EmailFilterCreate(BaseModel):
    require_attachment: bool = False
    sender_keywords: str | None = None
    subject_keywords: str | None = None
    skip_promotions_tab: bool = False

class EmailAccountCreate(BaseModel):
    provider: str
    email_address: EmailStr
    imap_host: str
    imap_port: int = Field(993, ge=1, le=65535)
    password: str = Field(..., min_length=1)
    filters: EmailFilterCreate | None = None
    ingestion_approach: str | None = None

    @field_validator("imap_host")
    @classmethod
    def validate_imap_host(cls, value: str) -> str:
        return validate_public_network_host(value, field_name="imap_host")

    @field_validator("imap_port")
    @classmethod
    def validate_imap_port(cls, value: int) -> int:
        if value != 993:
            raise ValueError("Only IMAP over SSL on port 993 is supported.")
        return value

class EmailAccountUpdate(BaseModel):
    provider: str
    email_address: EmailStr
    imap_host: str
    imap_port: int = Field(993, ge=1, le=65535)
    password: str | None = Field(default=None, min_length=1)  # optional, if omitted we keep existing password
    filters: EmailFilterCreate | None = None
    ingestion_approach: str | None = None

    @field_validator("imap_host")
    @classmethod
    def validate_imap_host(cls, value: str) -> str:
        return validate_public_network_host(value, field_name="imap_host")

    @field_validator("imap_port")
    @classmethod
    def validate_imap_port(cls, value: int) -> int:
        if value != 993:
            raise ValueError("Only IMAP over SSL on port 993 is supported.")
        return value

class EmailFilterResponse(BaseModel):
    id: UUID
    require_attachment: bool
    sender_keywords: str | None
    subject_keywords: str | None
    skip_promotions_tab: bool

    class Config:
        from_attributes = True

class EmailAccountResponse(BaseModel):
    id: UUID
    user_id: UUID
    provider: str
    email_address: str
    imap_host: str
    imap_port: int
    sync_status: str
    sync_error_msg: str | None = None
    last_synced_at: str | None = None
    created_at: str
    filters: list[EmailFilterResponse] = []

    class Config:
        from_attributes = True

class EmailSyncSettingResponse(BaseModel):
    id: UUID
    user_id: UUID
    poll_interval_minutes: int
    auto_extract_catalog: bool
    notify_on_new_catalog: bool
    ingestion_approach: str
    trusted_suppliers: str
    pending_approvals: str

    class Config:
        from_attributes = True

class EmailSyncSettingUpdate(BaseModel):
    poll_interval_minutes: int = Field(15, ge=5, le=1440)
    auto_extract_catalog: bool
    notify_on_new_catalog: bool
    ingestion_approach: str
    trusted_suppliers: str
    pending_approvals: str

import time
from collections import defaultdict

_IMAP_TEST_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_IMAP_FAIL_LOCKOUT: dict[str, float] = {}


def _check_imap_rate_limit(user_id: str, email_address: str) -> None:
    now = time.time()
    
    # Check mailbox lockout
    lockout_until = _IMAP_FAIL_LOCKOUT.get(email_address.lower(), 0.0)
    if now < lockout_until:
        wait_seconds = max(1, int(lockout_until - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts for this mailbox. Please try again in {wait_seconds} seconds.",
        )

    # User sliding window limit (max 5 requests per 60 seconds)
    user_attempts = [t for t in _IMAP_TEST_ATTEMPTS[user_id] if now - t < 60]
    _IMAP_TEST_ATTEMPTS[user_id] = user_attempts
    if len(user_attempts) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for mailbox testing. Please wait a minute before trying again.",
        )
    _IMAP_TEST_ATTEMPTS[user_id].append(now)


def _record_imap_failure(email_address: str) -> None:
    now = time.time()
    key = email_address.lower()
    fails = [t for t in _IMAP_TEST_ATTEMPTS[f"fail:{key}"] if now - t < 300]
    fails.append(now)
    _IMAP_TEST_ATTEMPTS[f"fail:{key}"] = fails
    if len(fails) >= 3:
        _IMAP_FAIL_LOCKOUT[key] = now + 300


# --- Helpers ---

def verify_imap_credentials(host: str, port: int, email_address: str, password: str) -> tuple[bool, str]:
    """Helper to test IMAP connection and credentials synchronously."""
    try:
        masked_user = email_address[:2] + "***" + email_address[email_address.find("@"):] if "@" in email_address else "user"
        logger.info("Testing IMAP connection to %s:%s for %s", host, port, masked_user)
        if port == 993:
            # Use SSL
            mail = imaplib.IMAP4_SSL(host, port, timeout=5)
        else:
            return False, "Only IMAP over SSL on port 993 is supported."
        
        try:
            mail.login(email_address, password)
            mail.logout()
            return True, "IMAP connection and login verified successfully."
        except imaplib.IMAP4.error:
            _record_imap_failure(email_address)
            logger.info("IMAP authentication failed for %s on %s:%s", masked_user, host, port)
            return False, "Unable to authenticate with the mail server. Verify your email and password/app password."
        except Exception:
            _record_imap_failure(email_address)
            logger.warning("IMAP login error for %s on %s:%s", masked_user, host, port, exc_info=True)
            return False, "Unable to authenticate with the mail server. Verify your email and password/app password."
    except Exception:
        logger.warning("Could not connect to IMAP server %s:%s", host, port, exc_info=True)
        return False, "Could not connect to the IMAP server. Verify the server hostname and port."


def queue_email_account_sync(account_id: UUID) -> str:
    from backend.app.tasks import poll_email_account

    try:
        task = poll_email_account.apply_async(args=[str(account_id)], retry=False)
        return task.id
    except Exception as e:
        logger.warning(f"Celery queueing failed for account {account_id}, running background fallback thread: {e}")
        import threading

        def _fallback_sync(acc_id: UUID):
            from backend.app.db import SessionLocal
            from backend.app.services.email_ingestion import EmailIngestionService
            with SessionLocal() as db:
                service = EmailIngestionService(db)
                try:
                    service.poll_account_inbox(acc_id)
                except Exception as ex:
                    logger.error(f"Fallback thread sync failed for account {acc_id}: {ex}")

        t = threading.Thread(target=_fallback_sync, args=(account_id,), daemon=True)
        t.start()
        return f"fallback-{account_id}"

# --- Endpoints ---

@router.post("/test", response_model=IMAPTestResponse)
def test_imap_connection(
    request: IMAPTestRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Test the IMAP credentials prior to saving them.
    Requires user authentication and enforces anti-bruteforce rate limits.
    """
    user_id = str(current_user.get("id", "anonymous"))
    _check_imap_rate_limit(user_id=user_id, email_address=request.email_address)

    success, message = verify_imap_credentials(
        host=request.imap_host,
        port=request.imap_port,
        email_address=request.email_address,
        password=request.password
    )
    return IMAPTestResponse(success=success, message=message)

@router.get("", response_model=list[EmailAccountResponse])
def list_email_accounts(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all connected email accounts for the current authenticated user."""
    user_uuid = UUID(current_user["id"])
    accounts = db.query(EmailAccount).filter(EmailAccount.user_id == user_uuid).all()
    
    response = []
    for acc in accounts:
        response.append(
            EmailAccountResponse(
                id=acc.id,
                user_id=acc.user_id,
                provider=acc.provider,
                email_address=acc.email_address,
                imap_host=acc.imap_host,
                imap_port=acc.imap_port,
                sync_status=acc.sync_status,
                sync_error_msg=acc.sync_error_msg,
                last_synced_at=acc.last_synced_at.isoformat() if acc.last_synced_at else None,
                created_at=acc.created_at.isoformat(),
                filters=[
                    EmailFilterResponse(
                        id=f.id,
                        require_attachment=f.require_attachment,
                        sender_keywords=f.sender_keywords,
                        subject_keywords=f.subject_keywords,
                        skip_promotions_tab=f.skip_promotions_tab
                    )
                    for f in acc.filters
                ]
            )
        )
    return response

@router.post("", response_model=EmailAccountResponse)
def save_email_account(
    request: EmailAccountCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Validate the credentials, then save the email account with encrypted passwords
    and its filters to the database.
    """
    # 1. Double check the credentials to avoid bad database state
    success, message = verify_imap_credentials(
        host=request.imap_host,
        port=request.imap_port,
        email_address=request.email_address,
        password=request.password
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot save: credential validation failed. {message}"
        )

    # 2. Encrypt password securely using Fernet
    encrypted = encrypt_password(request.password)

    try:
        user_uuid = UUID(current_user["id"])
        
        # 3. Create and add EmailAccount
        new_account = EmailAccount(
            user_id=user_uuid,
            provider=request.provider,
            email_address=request.email_address,
            imap_host=request.imap_host,
            imap_port=request.imap_port,
            encrypted_password=encrypted,
            sync_status="verified"
        )
        db.add(new_account)
        db.flush()  # Generate the ID for new_account so filters can reference it

        # 4. Handle optional filters
        if request.filters:
            f = request.filters
            new_filter = EmailFilter(
                email_account_id=new_account.id,
                require_attachment=f.require_attachment,
                sender_keywords=f.sender_keywords,
                subject_keywords=f.subject_keywords,
                skip_promotions_tab=f.skip_promotions_tab
            )
            db.add(new_filter)

        # 5. Handle global sync setting ingestion approach
        from backend.app.models import EmailSyncSetting
        sync_settings = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_uuid).first()
        if not sync_settings:
            sync_settings = EmailSyncSetting(
                user_id=user_uuid,
                ingestion_approach=request.ingestion_approach or "approach_1",
                trusted_suppliers="",
                pending_approvals=""
            )
            db.add(sync_settings)
        elif request.ingestion_approach:
            sync_settings.ingestion_approach = request.ingestion_approach

        db.commit()
        db.refresh(new_account)
        
        try:
            queue_email_account_sync(new_account.id)
            new_account.sync_status = "pending"
            db.commit()
            db.refresh(new_account)
        except Exception as e:
            logger.warning("Email account saved, but immediate sync queueing failed for %s: %s", new_account.id, e)
        
        return EmailAccountResponse(
            id=new_account.id,
            user_id=new_account.user_id,
            provider=new_account.provider,
            email_address=new_account.email_address,
            imap_host=new_account.imap_host,
            imap_port=new_account.imap_port,
            sync_status=new_account.sync_status,
            sync_error_msg=new_account.sync_error_msg,
            last_synced_at=new_account.last_synced_at.isoformat() if new_account.last_synced_at else None,
            created_at=new_account.created_at.isoformat(),
            filters=[
                EmailFilterResponse(
                    id=f.id,
                    require_attachment=f.require_attachment,
                    sender_keywords=f.sender_keywords,
                    subject_keywords=f.subject_keywords,
                    skip_promotions_tab=f.skip_promotions_tab
                )
                for f in new_account.filters
            ]
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving email account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving the email account."
        )

@router.get("/sync-settings", response_model=EmailSyncSettingResponse)
def get_sync_settings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Retrieve the global email sync settings for the user, creating a default entry if not found."""
    user_uuid = UUID(current_user["id"])
    from backend.app.models import EmailSyncSetting
    settings_row = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_uuid).first()
    if not settings_row:
        try:
            settings_row = EmailSyncSetting(
                user_id=user_uuid,
                poll_interval_minutes=15,  # Default to 15 minutes
                auto_extract_catalog=True,
                notify_on_new_catalog=True,
                ingestion_approach="approach_1",
                trusted_suppliers="",
                pending_approvals=""
            )
            db.add(settings_row)
            db.commit()
            db.refresh(settings_row)
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating default sync settings: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not initialize default sync settings."
            )
    return settings_row

@router.put("/sync-settings", response_model=EmailSyncSettingResponse)
def update_sync_settings(
    request: EmailSyncSettingUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update global sync settings for the user."""
    user_uuid = UUID(current_user["id"])
    from backend.app.models import EmailSyncSetting
    settings_row = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_uuid).first()
    if not settings_row:
        settings_row = EmailSyncSetting(
            user_id=user_uuid,
            poll_interval_minutes=15,
            ingestion_approach="approach_1",
            trusted_suppliers="",
            pending_approvals=""
        )
        db.add(settings_row)
        
    try:
        settings_row.poll_interval_minutes = request.poll_interval_minutes
        settings_row.auto_extract_catalog = request.auto_extract_catalog
        settings_row.notify_on_new_catalog = request.notify_on_new_catalog
        settings_row.ingestion_approach = request.ingestion_approach
        settings_row.trusted_suppliers = request.trusted_suppliers
        settings_row.pending_approvals = filter_trusted_pending_approvals(
            request.pending_approvals,
            request.trusted_suppliers,
        )
        db.commit()
        db.refresh(settings_row)

        return settings_row
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating sync settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating sync settings."
        )

@router.put("/{account_id}", response_model=EmailAccountResponse)
def update_email_account(
    account_id: UUID,
    request: EmailAccountUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update email account details, credentials and filters securely. Ensures tenant isolation."""
    user_uuid = UUID(current_user["id"])
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id, EmailAccount.user_id == user_uuid).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found or access denied."
        )
    
    # 1. Determine active password
    from backend.app.auth import decrypt_password
    if request.password:
        active_password = request.password
    else:
        try:
            active_password = decrypt_password(account.encrypted_password)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to decrypt existing password for verification."
            )

    # 2. Test Connection
    success, message = verify_imap_credentials(
        host=request.imap_host,
        port=request.imap_port,
        email_address=request.email_address,
        password=active_password
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential verification failed: {message}"
        )
    
    try:
        # 3. Update account details
        account.provider = request.provider
        account.email_address = request.email_address
        account.imap_host = request.imap_host
        account.imap_port = request.imap_port
        
        if request.password:
            account.encrypted_password = encrypt_password(request.password)
            
        account.sync_status = "verified"
        account.sync_error_msg = None
        
        # 4. Update or Create filters
        from backend.app.models import EmailFilter
        existing_filter = db.query(EmailFilter).filter(EmailFilter.email_account_id == account.id).first()
        if request.filters:
            f = request.filters
            if existing_filter:
                existing_filter.require_attachment = f.require_attachment
                existing_filter.sender_keywords = f.sender_keywords
                existing_filter.subject_keywords = f.subject_keywords
                existing_filter.skip_promotions_tab = f.skip_promotions_tab
            else:
                new_filter = EmailFilter(
                    email_account_id=account.id,
                    require_attachment=f.require_attachment,
                    sender_keywords=f.sender_keywords,
                    subject_keywords=f.subject_keywords,
                    skip_promotions_tab=f.skip_promotions_tab
                )
                db.add(new_filter)
        else:
            if existing_filter:
                db.delete(existing_filter)

        # 5. Update global sync settings ingestion approach
        from backend.app.models import EmailSyncSetting
        sync_settings = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_uuid).first()
        if not sync_settings:
            sync_settings = EmailSyncSetting(
                user_id=user_uuid,
                ingestion_approach=request.ingestion_approach or "approach_1",
                trusted_suppliers="",
                pending_approvals=""
            )
            db.add(sync_settings)
        elif request.ingestion_approach:
            sync_settings.ingestion_approach = request.ingestion_approach
                
        db.commit()
        db.refresh(account)
        
        return EmailAccountResponse(
            id=account.id,
            user_id=account.user_id,
            provider=account.provider,
            email_address=account.email_address,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            sync_status=account.sync_status,
            sync_error_msg=account.sync_error_msg,
            last_synced_at=account.last_synced_at.isoformat() if account.last_synced_at else None,
            created_at=account.created_at.isoformat(),
            filters=[
                EmailFilterResponse(
                    id=flt.id,
                    require_attachment=flt.require_attachment,
                    sender_keywords=flt.sender_keywords,
                    subject_keywords=flt.subject_keywords,
                    skip_promotions_tab=flt.skip_promotions_tab
                )
                for flt in account.filters
            ]
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating email account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the email account."
        )

@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_email_account(
    account_id: UUID,
    purge_data: bool = Query(False, description="Delete emails, extracted catalogue rows, certificates, and pending approvals from this mailbox."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Disconnect an email account. Optionally purge all ingested data for this mailbox."""
    user_uuid = UUID(current_user["id"])
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id, EmailAccount.user_id == user_uuid).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found or access denied."
        )
    
    try:
        storage_paths = _purge_mailbox_ingested_data(db, account) if purge_data else []
        db.delete(account)
        db.commit()
        _delete_storage_objects(storage_paths)
        return
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting email account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the email account."
        )

@router.post("/{account_id}/sync", response_model=EmailAccountResponse)
def trigger_sync_now(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Queue an immediate IMAP sync for the specified account."""
    user_uuid = UUID(current_user["id"])
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id, EmailAccount.user_id == user_uuid).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found or access denied."
        )
        
    try:
        queue_email_account_sync(account.id)
        account.sync_status = "pending"
        db.commit()
        db.refresh(account)
        
        return EmailAccountResponse(
            id=account.id,
            user_id=account.user_id,
            provider=account.provider,
            email_address=account.email_address,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            sync_status=account.sync_status,
            sync_error_msg=account.sync_error_msg,
            last_synced_at=account.last_synced_at.isoformat() if account.last_synced_at else None,
            created_at=account.created_at.isoformat(),
            filters=[
                EmailFilterResponse(
                    id=flt.id,
                    require_attachment=flt.require_attachment,
                    sender_keywords=flt.sender_keywords,
                    subject_keywords=flt.subject_keywords,
                    skip_promotions_tab=flt.skip_promotions_tab
                )
                for flt in account.filters
            ]
        )
    except Exception as e:
        logger.error(f"Error queueing sync task: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email sync worker is unavailable. Start Valkey and Celery, then try again."
        )




import secrets
import logging
import hashlib
from datetime import datetime, timedelta, UTC
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import exists, func, text
from pydantic import BaseModel, EmailStr, field_validator

from backend.app.db import get_db, get_supabase, SessionLocal
from backend.app.auth import get_current_admin
from backend.app.models import Profile, Supplier, CatalogItem, CatalogEmail, EmployeeInvitation, PasswordReset, EmailAccount, AIQueryLog, TenantAISetting
from backend.app.services.email_sender import send_transactional_email
from backend.app.config import get_settings
from backend.app.security import escape_html
from backend.app.schemas import validate_password_strength
from backend.app.rate_limiter import rate_limit_dependency
from backend.app.services.tenant_ai_settings import (
    DEFAULT_OPENROUTER_TEXT_MODEL,
    DEFAULT_OPENROUTER_VISION_MODEL,
    OPENROUTER_PROVIDER,
    encrypt_ai_api_key,
    validate_openrouter_api_key,
    validate_openrouter_model,
)
from fastapi import BackgroundTasks

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

class EmployeeInviteRequest(BaseModel):
    name: str
    email: EmailStr

class ResetPasswordCompleteRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_pwd(cls, v: str) -> str:
        return validate_password_strength(v)

class CompleteActivationRequest(BaseModel):
    token: str
    password: str
    name: str

    @field_validator("password")
    @classmethod
    def validate_pwd(cls, v: str) -> str:
        return validate_password_strength(v)


class AdminAISettingsResponse(BaseModel):
    provider: str = OPENROUTER_PROVIDER
    has_api_key: bool
    api_key_last4: str | None = None
    vision_model: str
    text_model: str


class AdminAISettingsUpdateRequest(BaseModel):
    api_key: str | None = None
    vision_model: str
    text_model: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return validate_openrouter_api_key(value)

    @field_validator("vision_model")
    @classmethod
    def validate_vision_model(cls, value: str) -> str:
        return validate_openrouter_model(value, "Vision model")

    @field_validator("text_model")
    @classmethod
    def validate_text_model(cls, value: str) -> str:
        return validate_openrouter_model(value, "Text model")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_lookup_values(token: str) -> list[str]:
    return [token_digest(token)]


# 1. Dashboard Metrics Endpoint
@router.get("/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db), current_user: dict = Depends(get_current_admin)):
    tenant_uuid = UUID(current_user["tenant_id"])
    
    # Total employees in their organisation
    employees = db.query(Profile).filter(Profile.tenant_id == tenant_uuid, Profile.role == "employee").all()
    total_employees = len(employees)
    
    # Organization user scope: Admin ID + all employee IDs under this tenant
    org_user_ids = [tenant_uuid] + [emp.id for emp in employees]
    
    # Total supplier emails processed for their workspace (admin + employees)
    total_emails = db.query(CatalogEmail).filter(
        CatalogEmail.tenant_id.in_(org_user_ids),
        CatalogEmail.processing_status == "completed",
        exists().where(CatalogItem.catalog_email_id == CatalogEmail.id),
    ).count()
    
    # AI queries today (within last 24h)
    twenty_four_hours_ago = datetime.now(UTC) - timedelta(days=1)
    queries_today = db.query(AIQueryLog).filter(
        AIQueryLog.tenant_id.in_(org_user_ids),
        AIQueryLog.created_at >= twenty_four_hours_ago
    ).count()
    
    return {
        "total_employees": total_employees,
        "total_emails_processed": total_emails,
        "ai_queries_today": queries_today
    }

# 2. Database Overview Metrics Endpoint
@router.get("/database-stats")
def get_database_stats(db: Session = Depends(get_db), current_user: dict = Depends(get_current_admin)):
    tenant_uuid = UUID(current_user["tenant_id"])
    
    employees = db.query(Profile).filter(Profile.tenant_id == tenant_uuid, Profile.role == "employee").all()
    org_user_ids = [tenant_uuid] + [emp.id for emp in employees]
    
    total_suppliers = db.query(Supplier).filter(Supplier.tenant_id.in_(org_user_ids)).distinct().count()
    total_ingredients = db.query(CatalogItem.ingredient_name).filter(CatalogItem.tenant_id.in_(org_user_ids)).distinct().count()
    
    # simple PgDatabase size fallback if not in postgres
    db_size_mb = 0.0
    try:
        size_query = db.execute(func.pg_database_size(func.current_database()))
        db_size_bytes = size_query.scalar() or 0
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
    except Exception:
        db_size_mb = 12.4 # Mock fallback if sqlite/local
        
    one_day_ago = datetime.now(UTC) - timedelta(days=1)
    one_month_ago = datetime.now(UTC) - timedelta(days=30)
    
    searches_day = db.query(AIQueryLog).filter(
        AIQueryLog.tenant_id.in_(org_user_ids),
        AIQueryLog.created_at >= one_day_ago
    ).count()
    
    searches_month = db.query(AIQueryLog).filter(
        AIQueryLog.tenant_id.in_(org_user_ids),
        AIQueryLog.created_at >= one_month_ago
    ).count()
    
    return {
        "total_suppliers": total_suppliers,
        "total_ingredients": total_ingredients,
        "database_size_mb": db_size_mb,
        "searches_per_day": searches_day,
        "searches_per_month": searches_month
    }


@router.get("/ai-settings", response_model=AdminAISettingsResponse)
def get_ai_settings(db: Session = Depends(get_db), current_user: dict = Depends(get_current_admin)):
    tenant_uuid = UUID(current_user["tenant_id"])
    setting = db.query(TenantAISetting).filter(TenantAISetting.tenant_id == tenant_uuid).first()
    return AdminAISettingsResponse(
        has_api_key=bool(setting and setting.encrypted_api_key),
        api_key_last4=setting.api_key_last4 if setting else None,
        vision_model=setting.vision_model if setting else DEFAULT_OPENROUTER_VISION_MODEL,
        text_model=setting.text_model if setting else DEFAULT_OPENROUTER_TEXT_MODEL,
    )


@router.put("/ai-settings", response_model=AdminAISettingsResponse)
def update_ai_settings(
    payload: AdminAISettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    tenant_uuid = UUID(current_user["tenant_id"])
    admin_uuid = UUID(current_user["id"])
    setting = db.query(TenantAISetting).filter(TenantAISetting.tenant_id == tenant_uuid).first()

    if setting is None and not payload.api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required before saving tenant AI settings.")

    if setting is None:
        setting = TenantAISetting(
            tenant_id=tenant_uuid,
            provider=OPENROUTER_PROVIDER,
            vision_model=payload.vision_model,
            text_model=payload.text_model,
            updated_by=admin_uuid,
        )
        db.add(setting)

    setting.provider = OPENROUTER_PROVIDER
    setting.vision_model = payload.vision_model
    setting.text_model = payload.text_model
    setting.updated_by = admin_uuid

    if payload.api_key:
        try:
            setting.encrypted_api_key = encrypt_ai_api_key(payload.api_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        setting.api_key_last4 = payload.api_key[-4:]

    db.commit()
    db.refresh(setting)

    return AdminAISettingsResponse(
        has_api_key=bool(setting.encrypted_api_key),
        api_key_last4=setting.api_key_last4,
        vision_model=setting.vision_model,
        text_model=setting.text_model,
    )

class AdminRegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    organisation: str

    @field_validator("name", "organisation")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Name and workspace name are required.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_pwd(cls, v: str) -> str:
        return validate_password_strength(v)

@router.post(
    "/register-admin",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_dependency(max_requests=5, window_seconds=600, scope="admin_register"))],
)
def register_admin(payload: AdminRegisterRequest, db: Session = Depends(get_db)):
    org_name = payload.organisation.strip()
    email = str(payload.email).strip().lower()

    # Verify that organisation does not already exist in database profiles
    existing_org = db.query(Profile).filter(func.lower(func.trim(Profile.organisation)) == org_name.lower()).first()
    if existing_org:
        logger.info("Registration rejected: organisation '%s' already exists", org_name)
        raise HTTPException(
            status_code=400,
            detail="A workspace or account with these details is already registered. Use a different email/workspace name or ask the superadmin to approve the existing request.",
        )

    existing_user_id = db.execute(text("SELECT id FROM auth.users WHERE LOWER(email) = LOWER(:email)"), {"email": email}).scalar()
    if existing_user_id:
        logger.info("Registration rejected: email '%s' already exists", email)
        raise HTTPException(
            status_code=400,
            detail="A workspace or account with these details is already registered. Use a different email/workspace name or ask the superadmin to approve the existing request.",
        )

    try:
        supabase_client = get_supabase()
        attributes = {
            "email": email,
            "password": payload.password,
            "email_confirm": True, # Auto-confirms email address (skips verification link)
            "user_metadata": {
                "full_name": payload.name.strip(),
                "role": "admin",
                "organisation": org_name
            }
        }
        supabase_client.auth.admin.create_user(attributes)
        return {"success": True, "message": "Workspace registered. Awaiting Superadmin approval."}
    except Exception as e:
        logger.error(f"Failed to register admin workspace: {e}")
        err_msg = str(e)
        if "already exists" in err_msg.lower() or "unique" in err_msg.lower():
            raise HTTPException(
                status_code=400,
                detail="A workspace or account with these details is already registered. Use a different email/workspace name or ask the superadmin to approve the existing request.",
            )
        raise HTTPException(status_code=500, detail="Failed to create admin workspace registration.")

# 3. Add Employee / Send Invite
@router.post("/employees/invite", status_code=status.HTTP_201_CREATED)
def invite_employee(
    payload: EmployeeInviteRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    admin_uuid = UUID(current_user["id"])
    tenant_uuid = UUID(current_user["tenant_id"])
    
    # Check if invitation already exists
    existing_invite = db.query(EmployeeInvitation).filter(
        EmployeeInvitation.email == payload.email
    ).first()
    if existing_invite:
        # Check if the user profile exists in the database
        user_id_val = db.execute(text("SELECT id FROM auth.users WHERE email = :email"), {"email": payload.email}).scalar()
        profile_exists = False
        if user_id_val:
            profile_exists = db.query(Profile).filter(Profile.id == user_id_val).first() is not None
            
        if profile_exists:
            p = db.query(Profile).filter(Profile.id == user_id_val).first()
            if p.status == "Disabled":
                raise HTTPException(status_code=400, detail="This account is deactivated. Please delete or reactivate it.")
            else:
                raise HTTPException(status_code=400, detail="An employee with this email address is already registered.")
        else:
            # The profile was deleted, so we can clean up the old invitation record to prevent UNIQUE constraint violation
            db.delete(existing_invite)
            db.commit()
         
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=2)
    
    new_invite = EmployeeInvitation(
        admin_id=admin_uuid,
        tenant_id=tenant_uuid,
        name=payload.name,
        email=payload.email,
        token=token_digest(token),
        expires_at=expires_at,
        status="Pending Activation"
    )
    db.add(new_invite)
    db.flush()
    
    admin_profile = db.query(Profile).filter(Profile.id == admin_uuid).first()
    org_name = admin_profile.organisation if (admin_profile and admin_profile.organisation) else "MediCORE"
    safe_payload_name = escape_html(payload.name)
    safe_org_name = escape_html(org_name)

    activation_link = f"{settings.frontend_origin}/activate?token={token}"
    email_html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#17211c;max-width:500px;margin:0 auto;padding:24px;border:1px solid #dce4df;border-radius:12px;">
      <h2 style="color:#0f7a5f;margin:0 0 16px 0;">You're invited to join MediCORE</h2>
      <p>Hi {safe_payload_name},</p>
      <p>You've been invited to use MediCORE by {safe_org_name}.</p>
      <p style="margin:24px 0;">
        <a href="{activation_link}" style="background-color:#0f7a5f;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;font-weight:600;display:inline-block;">Activate Account</a>
      </p>
      <p style="font-size:12px;color:#66736d;">This activation link expires in 2 hours. If you did not expect this invitation, you can safely ignore this email.</p>
      <hr style="border:none;border-top:1px solid #dce4df;margin:24px 0;" />
      <p style="font-size:12px;color:#66736d;margin:0;">Regards,<br>MediCORE Team</p>
    </div>
    """

    email_sent = send_transactional_email(payload.email, "You're invited to join MediCORE", email_html)
    if not email_sent:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invitation email could not be sent. Refresh the Gmail connection and try again.",
        )

    db.commit()
    return {"message": "Invitation sent successfully."}

# 4. Verify Invitation Token
@router.get(
    "/activate/verify",
    dependencies=[Depends(rate_limit_dependency(max_requests=15, window_seconds=600, scope="activate_verify"))],
)
def verify_activation_token(token: str, db: Session = Depends(get_db)):
    invite = db.query(EmployeeInvitation).filter(EmployeeInvitation.token.in_(token_lookup_values(token))).first()
    if not invite or invite.status != "Pending Activation" or invite.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invalid or expired activation link.")
    return {"email": invite.email, "name": invite.name}

# 4b. Complete Employee Account Activation without email confirmation
@router.post(
    "/activate/complete",
    dependencies=[Depends(rate_limit_dependency(max_requests=10, window_seconds=600, scope="activate_complete"))],
)
def complete_activation(payload: CompleteActivationRequest, db: Session = Depends(get_db)):
    invite = db.query(EmployeeInvitation).filter(EmployeeInvitation.token.in_(token_lookup_values(payload.token))).first()
    if not invite or invite.status != "Pending Activation" or invite.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invalid or expired activation link.")
        
    try:
        supabase_client = get_supabase()
        
        # We need organization name from the inviting admin's profile
        admin_profile = db.query(Profile).filter(Profile.id == invite.admin_id).first()
        org_name = admin_profile.organisation if (admin_profile and admin_profile.organisation) else "MediCORE"
        
        # Create user via Supabase admin auth API.
        # This allows setting email_confirm to True so that NO confirmation link is sent.
        attributes = {
            "email": invite.email,
            "password": payload.password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": payload.name,
                "role": "employee",
                "organisation": org_name
            }
        }
        
        supabase_client.auth.admin.create_user(attributes)
        
        # We can also verify that the trigger has updated invitation status to Active.
        # Just in case, let's commit/verify.
        # (The PostgreSQL trigger handle_new_user should have set status = 'Active')
        db.refresh(invite)
        if invite.status == "Pending Activation":
            invite.status = "Active"
            db.commit()
            
        return {"success": True, "message": "Employee account activated successfully."}
        
    except Exception as e:
        logger.error("Failed to create employee user in Supabase: %s", e)
        # If user already exists in auth.users, let's provide a friendly message.
        err_msg = str(e)
        if "already exists" in err_msg.lower() or "unique" in err_msg.lower():
            raise HTTPException(status_code=400, detail="An account with this email address has already been created.")
        raise HTTPException(status_code=500, detail="Failed to activate account.")


# 5. List Employees for current admin's organisation
@router.get("/employees")
def list_employees(db: Session = Depends(get_db), current_user: dict = Depends(get_current_admin)):
    tenant_uuid = UUID(current_user["tenant_id"])
    
    profiles = db.query(Profile).filter(Profile.tenant_id == tenant_uuid, Profile.role == "employee").all()
    profile_ids = [p.id for p in profiles]
    
    account_by_user = {
        account.user_id: account
        for account in (
            db.query(EmailAccount)
            .filter(EmailAccount.user_id.in_(profile_ids))
            .all()
            if profile_ids
            else []
        )
    }

    # Query registered email addresses from auth.users
    user_emails = {}
    if profile_ids:
        try:
            rows = db.execute(text("SELECT id, email FROM auth.users WHERE id = ANY(:ids)"), {"ids": profile_ids}).fetchall()
            user_emails = {row.id: row.email for row in rows}
        except Exception as e:
            logger.warning("Could not query auth.users directly for employee emails: %s", e)

    # Fallback lookup from EmployeeInvitation for any missing email
    invitations_by_tenant = db.query(EmployeeInvitation).filter(EmployeeInvitation.tenant_id == tenant_uuid).all()
    
    invitations = [inv for inv in invitations_by_tenant if inv.status == "Pending Activation"]
    
    employees_list = []
    
    # Render profiles
    for p in profiles:
        # Fetch email account last sync details
        email_account = account_by_user.get(p.id)
        last_sync = "Never"
        
        # Primary email resolution: auth.users email, email_account email, or "Not connected"
        resolved_email = user_emails.get(p.id) or (email_account.email_address if email_account else "Not connected")
        
        if str(p.id) == current_user["id"]:
            resolved_email = current_user["email"]
            last_sync = "N/A (Admin)"
        elif email_account:
            if email_account.sync_status == "error":
                last_sync = "Sync error"
            elif email_account.last_synced_at:
                # Format relative time
                diff = datetime.now(UTC) - email_account.last_synced_at.replace(tzinfo=UTC)
                if diff.days > 0:
                    last_sync = "Yesterday" if diff.days == 1 else f"{diff.days} days ago"
                elif diff.seconds >= 3600:
                    hours = diff.seconds // 3600
                    last_sync = "1 hour ago" if hours == 1 else f"{hours} hours ago"
                elif diff.seconds >= 60:
                    mins = diff.seconds // 60
                    last_sync = "1 minute ago" if mins == 1 else f"{mins} minutes ago"
                else:
                    last_sync = "Just now"

        employees_list.append({
            "id": str(p.id),
            "name": p.full_name,
            "email": resolved_email,
            "status": p.status,
            "role": p.role,
            "last_sync": last_sync
        })
        
    # Render invitations
    for inv in invitations:
        employees_list.append({
            "id": str(inv.id),
            "name": inv.name,
            "email": inv.email,
            "status": "Pending Activation",
            "role": "employee",
            "last_sync": "Never"
        })
        
    return employees_list

def async_remove_employee_cleanup(user_id: UUID):
    db = SessionLocal()
    try:
        db.query(EmailAccount).filter(EmailAccount.user_id == user_id).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Successfully finished background remove-clean-up for employee user_id {user_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in async_remove_employee_cleanup task: {e}")
    finally:
        db.close()


def async_delete_employee_cleanup(user_id: UUID, tenant_id: UUID):
    db = SessionLocal()
    try:
        from backend.app.models import EmailAccount, PasswordReset, EmailSyncSetting, EmployeeInvitation
        email_val = None
        try:
            email_val = db.execute(text("SELECT email FROM auth.users WHERE id = :id"), {"id": user_id}).scalar()
        except Exception as e:
            logger.warning(f"Could not resolve email from auth.users for user_id {user_id}: {e}")
        if email_val:
            db.query(EmployeeInvitation).filter(
                EmployeeInvitation.email == email_val,
                EmployeeInvitation.tenant_id == tenant_id,
            ).delete(synchronize_session=False)
        db.query(EmailAccount).filter(EmailAccount.user_id == user_id).delete(synchronize_session=False)
        db.query(PasswordReset).filter(PasswordReset.user_id == user_id).delete(synchronize_session=False)
        db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_id).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Successfully finished background delete-clean-up for employee user_id {user_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in async_delete_employee_cleanup task: {e}")
    finally:
        db.close()


# 6. Disable Employee / Remove Employee
@router.post("/employees/{user_id}/remove")
def remove_employee(
    user_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    tenant_uuid = UUID(current_user["tenant_id"])
    profile = db.query(Profile).filter(Profile.id == user_id, Profile.tenant_id == tenant_uuid).first()
    
    if not profile:
        # Check if this ID is a pending invitation
        invitation = db.query(EmployeeInvitation).filter(
            EmployeeInvitation.id == user_id,
            EmployeeInvitation.tenant_id == tenant_uuid
        ).first()
        if invitation:
            db.delete(invitation)
            db.commit()
            return {"message": "Pending employee invitation has been cancelled."}
        raise HTTPException(status_code=404, detail="Employee profile not found")
        
    if profile.id == UUID(current_user["id"]):
        raise HTTPException(status_code=400, detail="You cannot deactivate your own admin account.")
        
    # Disable status (fast update)
    profile.status = "Disabled"
    db.commit()
    
    # Process slow deletes asynchronously to release database locks and avoid API timeouts
    background_tasks.add_task(async_remove_employee_cleanup, user_id)
    
    return {"message": f"Employee {profile.full_name} has been deactivated."}


# Permanent Delete Employee
@router.post("/employees/{user_id}/delete")
def delete_employee(
    user_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    tenant_uuid = UUID(current_user["tenant_id"])
    profile = db.query(Profile).filter(Profile.id == user_id, Profile.tenant_id == tenant_uuid).first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Employee profile not found")
        
    if profile.id == UUID(current_user["id"]):
        raise HTTPException(status_code=400, detail="You cannot delete your own admin account.")
        
    # Delete profile synchronously (fast update)
    db.delete(profile)
    db.commit()
    
    # Run the cascading deletes and invitation clean-ups in background
    background_tasks.add_task(async_delete_employee_cleanup, user_id, tenant_uuid)
    
    return {"message": "Employee has been permanently deleted."}

# 7. Reset Password Trigger
@router.post("/employees/{user_id}/reset-password")
def reset_password(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    tenant_uuid = UUID(current_user["tenant_id"])
    profile = db.query(Profile).filter(Profile.id == user_id, Profile.tenant_id == tenant_uuid).first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Employee profile not found")
        
    # Invalidate previous pending resets for this user
    db.query(PasswordReset).filter(PasswordReset.user_id == user_id, PasswordReset.status == "Pending").update(
        {PasswordReset.status: "Expired"}, synchronize_session=False
    )
    
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=2)
    
    reset_record = PasswordReset(
        user_id=user_id,
        token=token_digest(token),
        expires_at=expires_at,
        status="Pending"
    )
    db.add(reset_record)
    db.flush()
    
    # Retrieve user email by looking up Supabase or mock user record
    # Since email details are in Supabase auth, we'll try to retrieve the email address.
    user_email = ""
    try:
        supabase_client = get_supabase()
        response = supabase_client.auth.admin.get_user_by_id(str(user_id))
        if response and response.user:
            user_email = response.user.email
    except Exception:
        # Fallback to connected email search
        email_acct = db.query(EmailAccount).filter(EmailAccount.user_id == user_id).first()
        if email_acct:
            user_email = email_acct.email_address
            
    if not user_email:
        raise HTTPException(status_code=400, detail="Could not determine user email for password reset notification.")
        
    reset_link = f"{settings.frontend_origin}/reset-password?token={token}"
    safe_profile_name = escape_html(profile.full_name)
    email_html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#17211c;max-width:500px;margin:0 auto;padding:24px;border:1px solid #dce4df;border-radius:12px;">
      <h2 style="color:#0f7a5f;margin:0 0 16px 0;">Reset Your MediCORE Password</h2>
      <p>Hi {safe_profile_name},</p>
      <p>Your administrator has requested a password reset for your MediCORE account.</p>
      <p style="margin:24px 0;">
        <a href="{reset_link}" style="background-color:#0f7a5f;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;font-weight:600;display:inline-block;">Reset Password</a>
      </p>
      <p style="font-size:12px;color:#66736d;">This password reset link expires in 2 hours. If you did not request this, you can ignore this email.</p>
      <hr style="border:none;border-top:1px solid #dce4df;margin:24px 0;" />
      <p style="font-size:12px;color:#66736d;margin:0;">Regards,<br>MediCORE Team</p>
    </div>
    """

    email_sent = send_transactional_email(user_email, "Reset your MediCORE password", email_html)
    if not email_sent:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Password reset email could not be sent. Please check SMTP/network configuration and try again.",
        )

    db.commit()
    return {"message": "Password reset link emailed successfully."}

# 8. Verify Password Reset Token
@router.get(
    "/reset-password/verify",
    dependencies=[Depends(rate_limit_dependency(max_requests=15, window_seconds=600, scope="reset_verify"))],
)
def verify_reset_token(token: str, db: Session = Depends(get_db)):
    reset = db.query(PasswordReset).filter(PasswordReset.token.in_(token_lookup_values(token)), PasswordReset.status == "Pending").first()
    if not reset or reset.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invalid or expired password reset link.")
    return {"verified": True}

# 9. Complete Password Reset
@router.post(
    "/reset-password/complete",
    dependencies=[Depends(rate_limit_dependency(max_requests=10, window_seconds=600, scope="reset_complete"))],
)
def complete_password_reset(payload: ResetPasswordCompleteRequest, db: Session = Depends(get_db)):
    reset = db.query(PasswordReset).filter(PasswordReset.token.in_(token_lookup_values(payload.token)), PasswordReset.status == "Pending").first()
    if not reset or reset.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
        
    try:
        supabase_client = get_supabase()
        # Update user password in Supabase Auth using admin API
        supabase_client.auth.admin.update_user_by_id(
            str(reset.user_id),
            {"password": payload.password}
        )
        # Mark token as Used
        reset.status = "Used"
        db.commit()
        return {"success": True, "message": "Password updated successfully."}
    except Exception as e:
        logger.error("Failed to update password in Supabase: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reset password.")

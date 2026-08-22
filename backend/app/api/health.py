from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.auth import get_current_user
from backend.app.models import TenantAISetting
from backend.app.services.tenant_ai_settings import (
    DEFAULT_OPENROUTER_TEXT_MODEL,
    DEFAULT_OPENROUTER_VISION_MODEL,
    OPENROUTER_PROVIDER,
    ai_settings_tenant_id,
)

router = APIRouter()


from pydantic import BaseModel

class ProfileUpdateRequest(BaseModel):
    full_name: str


class CurrentAISettingsResponse(BaseModel):
    provider: str = OPENROUTER_PROVIDER
    has_api_key: bool
    api_key_last4: str | None = None
    vision_model: str
    text_model: str

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ocr")
def health_ocr() -> dict:
    from backend.app.pipeline.extraction.text_ocr import check_ocr_readiness

    result = check_ocr_readiness()
    if result.get("status") != "ready":
        raise HTTPException(status_code=503, detail=result)
    return result


@router.get("/api/profile")
def get_user_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
) -> dict:
    from uuid import UUID
    from backend.app.models import Profile

    user_uuid = UUID(current_user["id"])
    profile = db.query(Profile).filter(Profile.id == user_uuid).first()
    if profile:
        return {
            "id": str(profile.id),
            "full_name": profile.full_name,
            "organisation": profile.organisation or "MediCORE Central",
            "role": profile.role,
            "status": profile.status,
            "email": current_user.get("email")
        }
    return {
        "id": current_user["id"],
        "full_name": current_user["email"].split("@")[0],
        "organisation": "MediCORE Central",
        "role": current_user["role"],
        "status": "Active",
        "email": current_user.get("email")
    }


@router.get("/api/ai-settings/current", response_model=CurrentAISettingsResponse)
def get_current_ai_settings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> CurrentAISettingsResponse:
    tenant_uuid = UUID(current_user["tenant_id"])
    settings_tenant_id = ai_settings_tenant_id(db, tenant_uuid)
    setting = db.query(TenantAISetting).filter(TenantAISetting.tenant_id == settings_tenant_id).first()
    return CurrentAISettingsResponse(
        has_api_key=bool(setting and setting.encrypted_api_key),
        api_key_last4=setting.api_key_last4 if setting else None,
        vision_model=setting.vision_model if setting else DEFAULT_OPENROUTER_VISION_MODEL,
        text_model=setting.text_model if setting else DEFAULT_OPENROUTER_TEXT_MODEL,
    )


@router.post("/api/profile")
def update_user_profile(
    payload: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
) -> dict:
    from uuid import UUID
    from backend.app.models import Profile

    user_uuid = UUID(current_user["id"])
    profile = db.query(Profile).filter(Profile.id == user_uuid).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    profile.full_name = payload.full_name.strip()
    db.commit()
    db.refresh(profile)
    
    return {
        "id": str(profile.id),
        "full_name": profile.full_name,
        "organisation": profile.organisation or "MediCORE Central",
        "role": profile.role,
        "status": profile.status,
        "email": current_user.get("email")
    }

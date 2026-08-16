from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.auth import get_current_user

router = APIRouter()


from pydantic import BaseModel

class ProfileUpdateRequest(BaseModel):
    full_name: str

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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

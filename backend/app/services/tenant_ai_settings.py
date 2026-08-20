import base64
import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import Profile, TenantAISetting

OPENROUTER_PROVIDER = "openrouter"
DEFAULT_OPENROUTER_TEXT_MODEL = "openai/gpt-4o-mini"
DEFAULT_OPENROUTER_VISION_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{1,254}$")


@dataclass(frozen=True)
class TenantOpenRouterConfig:
    api_key: str
    text_model: str
    vision_model: str


def get_ai_settings_fernet() -> Fernet:
    raw = get_settings().ai_settings_fernet_key
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            hashed = hashlib.sha256(raw.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(hashed))
    raise RuntimeError("AI_SETTINGS_FERNET_KEY is required for tenant OpenRouter settings encryption.")


def encrypt_ai_api_key(api_key: str) -> str:
    return get_ai_settings_fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_ai_api_key(encrypted_api_key: str) -> str:
    return get_ai_settings_fernet().decrypt(encrypted_api_key.encode("utf-8")).decode("utf-8")


def validate_openrouter_api_key(api_key: str) -> str:
    cleaned = api_key.strip()
    if not cleaned:
        raise ValueError("OpenRouter API key is required.")
    if len(cleaned) < 20 or len(cleaned) > 500:
        raise ValueError("OpenRouter API key length is invalid.")
    if any(char.isspace() for char in cleaned):
        raise ValueError("OpenRouter API key cannot contain whitespace.")
    return cleaned


def validate_openrouter_model(model: str, field_name: str) -> str:
    cleaned = model.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required.")
    if not MODEL_ID_RE.fullmatch(cleaned):
        raise ValueError(f"{field_name} must be a valid OpenRouter model ID.")
    if "/" not in cleaned:
        raise ValueError(f"{field_name} must include an OpenRouter provider prefix, for example openai/gpt-4o-mini.")
    return cleaned


def ai_settings_tenant_id(db: Session, tenant_id: UUID) -> UUID:
    profile = db.query(Profile).filter(Profile.id == tenant_id).first()
    if profile and profile.role == "employee" and profile.tenant_id:
        return profile.tenant_id
    return tenant_id


def get_tenant_openrouter_config(db: Session | None, tenant_id: UUID | str | None) -> TenantOpenRouterConfig | None:
    if db is None or tenant_id is None:
        return None
    settings_tenant_id = ai_settings_tenant_id(db, UUID(str(tenant_id)))
    setting = db.query(TenantAISetting).filter(TenantAISetting.tenant_id == settings_tenant_id).first()
    if not setting or setting.provider != OPENROUTER_PROVIDER or not setting.encrypted_api_key:
        return None
    api_key = decrypt_ai_api_key(setting.encrypted_api_key)
    text_model = validate_openrouter_model(setting.text_model, "Text model")
    vision_model = validate_openrouter_model(setting.vision_model, "Vision model")
    return TenantOpenRouterConfig(api_key=api_key, text_model=text_model, vision_model=vision_model)

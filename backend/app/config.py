from functools import lru_cache
from pathlib import Path

from urllib.parse import urlparse, urlunparse

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    app_name: str = "MediCORE"
    api_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:3000"
    mock_data_enabled: bool = False

    supabase_url: AnyHttpUrl = "https://example.supabase.co"
    supabase_service_role_key: str = Field(default="replace-me", repr=False)
    supabase_storage_bucket: str = "catalog-pdfs"
    mailbox_fernet_key: str = Field(default="", repr=False)
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/postgres", repr=False)
    ai_readonly_database_url: str = Field(default="", repr=False)
    supabase_db_host: str = ""
    supabase_db_port: int = 5432
    supabase_db_name: str = "postgres"
    supabase_db_user: str = "postgres"
    supabase_db_password: str = Field(default="", repr=False)
    supabase_pooler_host: str = ""
    supabase_pooler_port: int = 6543
    supabase_pooler_user: str = ""

    valkey_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    cerebras_api_key: str = Field(default="", repr=False)
    cerebras_model: str = "llama-3.3-70b"
    cerebras_base_url: str = "https://api.cerebras.ai/v1"

    openrouter_api_key: str = Field(default="", repr=False)
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "MediCORE"

    email_mode: str = "imap"
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = Field(default="", repr=False)
    imap_mailbox: str = "INBOX"

    gmail_webhook_token: str = Field(default="", repr=False)
    gmail_oauth_token: str = Field(default="", repr=False)
    gmail_user_id: str = "me"
    google_project_id: str = ""
    google_pubsub_topic: str = ""
    google_client_id: str = Field(default="", repr=False)
    google_client_secret: str = Field(default="", repr=False)
    google_refresh_token: str = Field(default="", repr=False)

    transactional_email_provider: str = "smtp"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_sender: str = "medicore.ai@gmail.com"
    gmail_api_sender: str = ""
    superadmin_email_id: str = "prisik.da45@gmail.com"

    @property
    def queue_url(self) -> str:
        configured_url = self.valkey_url or self.redis_url
        parsed_url = urlparse(configured_url)
        if (
            self.environment.lower() != "production"
            and parsed_url.hostname == "valkey"
            and not Path("/.dockerenv").exists()
        ):
            return urlunparse(
                parsed_url._replace(netloc=parsed_url.netloc.replace("valkey", "localhost", 1))
            )
        return configured_url

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment.lower() != "production":
            return self

        missing: list[str] = []
        if self.supabase_service_role_key in {"", "replace-me"}:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if not self.mailbox_fernet_key:
            missing.append("MAILBOX_FERNET_KEY")
        if self.cerebras_api_key in {"", "replace-me"}:
            missing.append("CEREBRAS_API_KEY")
        if self.openrouter_api_key in {"", "replace-me"}:
            missing.append("OPENROUTER_API_KEY")
        if not self.gmail_webhook_token:
            missing.append("GMAIL_WEBHOOK_TOKEN")
        if self.frontend_origin.startswith("http://"):
            missing.append("FRONTEND_ORIGIN must use https:// in production")
        if not self.ai_readonly_database_url:
            missing.append("AI_READONLY_DATABASE_URL")
        if self.transactional_email_provider.lower() == "gmail_api":
            if not self.google_client_id:
                missing.append("GOOGLE_CLIENT_ID")
            if not self.google_client_secret:
                missing.append("GOOGLE_CLIENT_SECRET")
            if not self.google_refresh_token:
                missing.append("GOOGLE_REFRESH_TOKEN")
            if not (self.gmail_api_sender or self.smtp_sender):
                missing.append("GMAIL_API_SENDER or SMTP_SENDER")
        queue_url = self.queue_url
        parsed_queue_url = urlparse(queue_url)
        if parsed_queue_url.hostname in {"localhost", "127.0.0.1"}:
            missing.append("VALKEY_URL must point to the production Valkey service")
        if not parsed_queue_url.password:
            missing.append("VALKEY_URL must include a password in production")

        if missing:
            raise ValueError("Invalid production configuration: " + ", ".join(missing))
        return self



@lru_cache
def get_settings() -> Settings:
    return Settings()

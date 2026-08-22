import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("idx_suppliers_tenant_email_domain", "tenant_id", "email_domain"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(255))
    email_domain: Mapped[str] = mapped_column(String(255), index=True)
    country: Mapped[str] = mapped_column(String(100), default="Unknown", server_default="Unknown", nullable=False)
    last_email_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certifications: Mapped[str | None] = mapped_column(Text)

    emails: Mapped[list["CatalogEmail"]] = relationship(back_populates="supplier")


class CatalogEmail(Base):
    __tablename__ = "catalog_emails"
    __table_args__ = (
        UniqueConstraint("tenant_id", "raw_email_id", name="uq_catalog_emails_tenant_raw_email_id"),
        Index("idx_catalog_emails_tenant_received", "tenant_id", "received_at"),
        Index("idx_catalog_emails_supplier_id", "supplier_id"),
        Index("idx_catalog_emails_status", "tenant_id", "processing_status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_email_id: Mapped[str] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    body_preview: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String(50), default="queued")
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Supplier] = relationship(back_populates="emails")


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    __table_args__ = (
        Index("idx_catalog_items_catalog_email_id", "catalog_email_id"),
        Index("idx_catalog_items_tenant_supplier", "tenant_id", "supplier_id"),
        Index("idx_catalog_items_ingredient", "tenant_id", "ingredient_name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    catalog_email_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_emails.id"))
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    ingredient_name: Mapped[str] = mapped_column(String(255))
    price_per_unit: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="")
    available_qty: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moq: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        Index("idx_profiles_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    organisation: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text, default="member")
    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="Active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    __table_args__ = (
        Index("idx_email_accounts_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text)
    email_address: Mapped[str] = mapped_column(Text)
    imap_host: Mapped[str] = mapped_column(Text)
    imap_port: Mapped[int] = mapped_column(Integer)
    encrypted_password: Mapped[str] = mapped_column(Text)
    sync_status: Mapped[str] = mapped_column(Text, default="pending")
    sync_error_msg: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filters: Mapped[list["EmailFilter"]] = relationship(back_populates="email_account", cascade="all, delete-orphan")


class EmailFilter(Base):
    __tablename__ = "email_filters"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_account_id: Mapped[UUID] = mapped_column(ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False)
    require_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    sender_keywords: Mapped[str | None] = mapped_column(Text)
    subject_keywords: Mapped[str | None] = mapped_column(Text)
    skip_promotions_tab: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    email_account: Mapped[EmailAccount] = relationship(back_populates="filters")


class EmailSyncSetting(Base):
    __tablename__ = "email_sync_settings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    auto_extract_catalog: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_new_catalog: Mapped[bool] = mapped_column(Boolean, default=True)
    ingestion_approach: Mapped[str] = mapped_column(Text, default="approach_1")
    trusted_suppliers: Mapped[str] = mapped_column(Text, default="")
    pending_approvals: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantAISetting(Base):
    __tablename__ = "tenant_ai_settings"

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default="openrouter", server_default="openrouter", nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    api_key_last4: Mapped[str | None] = mapped_column(String(8))
    vision_model: Mapped[str] = mapped_column(String(255), nullable=False)
    text_model: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EmployeeInvitation(Base):
    __tablename__ = "employee_invitations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    token: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="Pending Activation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIQueryLog(Base):
    __tablename__ = "ai_query_logs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    query_text: Mapped[str] = mapped_column(Text)
    operation_type: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="Pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



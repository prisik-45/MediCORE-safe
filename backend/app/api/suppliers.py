from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from uuid import UUID

from backend.app.db import get_db
from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.auth import get_current_user

router = APIRouter()


@router.get("")
def list_suppliers(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
) -> list[dict]:
    user_uuid = UUID(current_user["tenant_id"])
    item_count_subq = (
        select(func.count(CatalogItem.id))
        .where(
            CatalogItem.supplier_id == Supplier.id,
            CatalogItem.tenant_id == user_uuid,
        )
        .scalar_subquery()
    )
    last_catalog_subq = (
        select(func.max(CatalogEmail.received_at))
        .where(
            CatalogEmail.supplier_id == Supplier.id,
            CatalogEmail.tenant_id == user_uuid,
            CatalogEmail.processing_status.in_(["completed", "partial", "certificate"]),
        )
        .scalar_subquery()
    )
    stmt = select(
        Supplier,
        item_count_subq.label("item_count"),
        last_catalog_subq.label("last_catalog_at"),
    ).where(
        Supplier.tenant_id == user_uuid,
        item_count_subq > 0,
    )

    rows = db.execute(stmt.order_by(Supplier.name.asc()))
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "email_domain": row.email_domain,
            "country": row.country or "Unknown",
            "last_email_date": last_catalog_at or row.last_email_date,
            "certifications": row.certifications,
            "item_count": int(item_count or 0),
        }
        for row, item_count, last_catalog_at in rows
    ]

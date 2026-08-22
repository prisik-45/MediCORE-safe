import logging
import re
from difflib import SequenceMatcher
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session
from uuid import UUID, uuid4

from backend.app.config import get_settings
from backend.app.db import ensure_supabase_storage_bucket, get_db, get_supabase
from backend.app.models import CatalogEmail, CatalogItem, EmailAccount, EmailSyncSetting, Supplier
from backend.app.auth import get_current_user
from backend.app.file_validator import (
    CERTIFICATE_ALLOWED_EXTENSIONS,
    MAX_CERTIFICATE_UPLOAD_BYTES,
    read_bounded_upload_file,
    sanitize_filename,
    validate_document_bytes,
)
from backend.app.schemas import clean_optional_text

router = APIRouter()
logger = logging.getLogger(__name__)


def nullable_float(value):
    return float(value) if value is not None else None


def display_value(raw_payload: dict | None, key: str):
    return clean_optional_text((raw_payload or {}).get(key))


def certificate_pdfs(raw_payload: dict | None) -> list[dict]:
    values = (raw_payload or {}).get("certificate_pdfs")
    if not isinstance(values, list):
        return []
    pdfs: list[dict] = []
    for row in values:
        if not isinstance(row, dict):
            continue
        storage_path = clean_optional_text(row.get("storage_path"))
        url = clean_optional_text(row.get("url"))
        if not storage_path and not url:
            continue
        pdfs.append(
            {
                "name": clean_optional_text(row.get("name")) or "Certificate PDF",
                "url": url,
                "storage_path": storage_path,
                "type": clean_optional_text(row.get("type")) or "Certificate",
            }
        )
    return pdfs


def canonical_search_text(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def search_tokens(value: object) -> list[str]:
    return [
        token
        for token in canonical_search_text(value).split()
        if len(token) >= 2 and token not in {"price", "qty", "item", "supplier", "find", "show", "best", "for", "the", "and"}
    ]


def row_relevance(row: dict, query: str | None) -> float:
    if not query:
        return 0.0
    needle = canonical_search_text(query)
    name = canonical_search_text(row.get("ingredient_name"))
    if not needle or not name:
        return 0.0

    score = 0.0
    if name == needle:
        score += 1000
    if needle in name:
        score += 750
    tokens = search_tokens(query)
    if tokens:
        name_tokens = set(name.split())
        matched = sum(1 for token in tokens if token in name_tokens or any(token in name_token for name_token in name_tokens))
        score += (matched / len(tokens)) * 300
        if matched == len(tokens):
            score += 150
    score += SequenceMatcher(None, needle, name).ratio() * 100
    return score


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


def delete_storage_object(object_path: str | None) -> None:
    if not object_path:
        return
    try:
        get_supabase().storage.from_(get_settings().supabase_storage_bucket).remove([object_path])
    except Exception:
        logger.warning("Failed to delete catalog attachment object %s", object_path, exc_info=True)


def certificate_storage_paths(raw_payload: dict | None) -> list[str]:
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


@router.get("/emails")
def list_catalog_emails(
    db: Session = Depends(get_db),
    limit: int = Query(10000, ge=1, le=10000),
    current_user: dict = Depends(get_current_user)
) -> list[dict]:
    user_uuid = UUID(current_user["tenant_id"])
    item_count_subq = (
        select(func.count(CatalogItem.id))
        .where(CatalogItem.catalog_email_id == CatalogEmail.id)
        .scalar_subquery()
    )
    stmt = (
        select(CatalogEmail, Supplier.name, Supplier.email_domain, item_count_subq.label("item_count"))
        .outerjoin(Supplier, Supplier.id == CatalogEmail.supplier_id)
        .where(
            CatalogEmail.tenant_id == user_uuid,
            CatalogEmail.processing_status != "deleted",
            # Certificate-only emails are archived in Supabase Storage and
            # linked to catalogue rows; they are not inbox messages.
            CatalogEmail.processing_status != "certificate",
        )
    )
    stmt = stmt.order_by(CatalogEmail.received_at.desc()).limit(limit)
    return [
        {
            "id": str(email.id),
            "supplier_name": supplier_name or email.sender_address or "Skipped email",
            "email_domain": email_domain or email.sender_address,
            "received_at": email.received_at,
            "subject": email.subject,
            "pdf_url": email.pdf_url,
            "body_preview": email.body_preview,
            "processing_status": email.processing_status,
            "item_count": int(item_count or 0),
            "duplicate_count": int(getattr(email, "duplicate_count", 0) or 0),
        }
        for email, supplier_name, email_domain, item_count in db.execute(stmt)
    ]


@router.get("/items")
def list_catalog_items(
    db: Session = Depends(get_db),
    q: str | None = None,
    limit: int = Query(10000, ge=1, le=10000),
    latest_only: bool = Query(True),
    catalog_email_id: UUID | None = Query(None),
    current_user: dict = Depends(get_current_user)
) -> list[dict]:
    user_uuid = UUID(current_user["tenant_id"])
    stmt = (
        select(CatalogItem, Supplier.name, Supplier.email_domain, Supplier.country, CatalogEmail.received_at, None)
        .join(Supplier, Supplier.id == CatalogItem.supplier_id)
        .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
    )
    if latest_only and catalog_email_id is None:
        latest_items = (
            select(
                CatalogItem.id.label("item_id"),
                func.row_number().over(
                    partition_by=(
                        CatalogItem.supplier_id,
                        CatalogItem.ingredient_name,
                        CatalogItem.raw_payload["specification"].astext,
                    ),
                    order_by=(
                        CatalogEmail.received_at.desc(),
                        CatalogItem.raw_payload["is_updated"].as_boolean().desc().nullslast(),
                        CatalogItem.id.desc(),
                    ),
                ).label("row_number"),
                func.count(CatalogItem.id).over(
                    partition_by=(
                        CatalogItem.supplier_id,
                        CatalogItem.ingredient_name,
                        CatalogItem.raw_payload["specification"].astext,
                    ),
                ).label("history_count"),
            )
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .where(
                CatalogItem.tenant_id == user_uuid,
                CatalogEmail.processing_status.in_(["completed", "partial", "certificate"]),
            )
            .subquery()
        )
        stmt = (
            select(CatalogItem, Supplier.name, Supplier.email_domain, Supplier.country, CatalogEmail.received_at, latest_items.c.history_count)
            .join(Supplier, Supplier.id == CatalogItem.supplier_id)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
        )
        stmt = stmt.join(
            latest_items,
            and_(
                latest_items.c.item_id == CatalogItem.id,
                latest_items.c.row_number == 1,
            ),
        )
    stmt = stmt.where(
        CatalogItem.tenant_id == user_uuid,
        CatalogEmail.processing_status.in_(["completed", "partial", "certificate"]),
    )
    if catalog_email_id is not None:
        stmt = stmt.where(CatalogItem.catalog_email_id == catalog_email_id)
    if q:
        tokens = search_tokens(q)
        if tokens:
            stmt = stmt.where(
                and_(*[CatalogItem.ingredient_name.ilike(f"%{token}%") for token in tokens])
            )
        else:
            stmt = stmt.where(CatalogItem.ingredient_name.ilike(f"%{q}%"))
    stmt = stmt.order_by(CatalogItem.ingredient_name.asc()).limit(limit)
    rows = [
        {
            "id": str(item.id),
            "catalog_email_id": str(item.catalog_email_id) if item.catalog_email_id else None,
            "supplier_name": supplier_name,
            "email_domain": email_domain,
            "country": (
                country
                if country and country != "Unknown"
                else (display_value(item.raw_payload, "country_of_origin") or display_value(item.raw_payload, "country") or "Unknown")
            ),
            "ingredient_name": item.ingredient_name,
            "specification": display_value(item.raw_payload, "specification"),
            "price_per_unit": nullable_float(item.price_per_unit),
            "currency": item.currency,
            "available_qty": nullable_float(item.available_qty),
            "unit": item.unit,
            "valid_until": item.valid_until,
            "lead_time_days": getattr(item, "lead_time_days", None) if getattr(item, "lead_time_days", None) is not None else (item.raw_payload or {}).get("lead_time_days"),
            "lead_time_text": display_value(item.raw_payload, "lead_time_text"),
            "moq": getattr(item, "moq", None) if getattr(item, "moq", None) is not None else (item.raw_payload or {}).get("moq"),
            "pack_size": display_value(item.raw_payload, "pack_size"),
            "price_display": display_value(item.raw_payload, "price_display"),
            "quantity_display": display_value(item.raw_payload, "quantity_display"),
            "moq_display": display_value(item.raw_payload, "moq_display"),
            "source_document": display_value(item.raw_payload, "source_document"),
            "certificate_pdfs": certificate_pdfs(item.raw_payload),
            "is_updated": bool((item.raw_payload or {}).get("is_updated")) or bool(history_count and history_count > 1),
            "received_at": received_at,
        }
        for item, supplier_name, email_domain, country, received_at, history_count in db.execute(stmt)
    ]
    if q:
        rows.sort(
            key=lambda row: (
                -row_relevance(row, q),
                str(row.get("ingredient_name") or "").lower(),
                row.get("price_per_unit") if row.get("price_per_unit") is not None else float("inf"),
            )
        )
    return rows


@router.get("/certificate-url")
def certificate_url(
    storage_path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    path = clean_optional_text(storage_path)
    if not path:
        raise HTTPException(status_code=400, detail="Certificate storage path is required.")
    user_uuid = UUID(current_user["tenant_id"])
    allowed = False
    for (raw_payload,) in db.query(CatalogItem.raw_payload).filter(CatalogItem.tenant_id == user_uuid):
        if path in certificate_storage_paths(raw_payload):
            allowed = True
            break
    if not allowed:
        raise HTTPException(status_code=404, detail="Certificate PDF could not be opened.")
    try:
        result = get_supabase().storage.from_(get_settings().supabase_storage_bucket).create_signed_url(
            path,
            60 * 60,
        )
        signed_url = None
        if isinstance(result, dict):
            signed_url = clean_optional_text(result.get("signedURL") or result.get("signed_url") or result.get("url"))
        else:
            signed_url = clean_optional_text(
                getattr(result, "signed_url", None)
                or getattr(result, "signedURL", None)
                or getattr(result, "url", None)
            )
        if not signed_url:
            raise RuntimeError("Supabase did not return a signed URL.")
        return {"url": signed_url, "expires_in": 60 * 60}
    except Exception as exc:
        logger.warning("Failed creating signed certificate URL for %s", path, exc_info=True)
        raise HTTPException(status_code=404, detail="Certificate PDF could not be opened.") from exc


@router.get("/sync-diagnostics")
def sync_diagnostics(
    db: Session = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
) -> dict:
    import json

    tenant_uuid = UUID(current_user["tenant_id"])
    user_uuid = UUID(current_user["id"])

    accounts = db.query(EmailAccount).filter(EmailAccount.user_id == user_uuid).all()
    sync_setting = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_uuid).first()
    pending_approvals: list[dict] = []
    if sync_setting:
        try:
            parsed = json.loads(sync_setting.pending_approvals or "[]")
            pending_approvals = [item for item in parsed if isinstance(item, dict)]
        except Exception:
            pending_approvals = []

    email_rows = (
        db.query(
            CatalogEmail,
            Supplier.name.label("supplier_name"),
            func.count(CatalogItem.id).label("item_count"),
        )
        .outerjoin(Supplier, Supplier.id == CatalogEmail.supplier_id)
        .outerjoin(CatalogItem, CatalogItem.catalog_email_id == CatalogEmail.id)
        .filter(CatalogEmail.tenant_id == tenant_uuid)
        .group_by(CatalogEmail.id, Supplier.name)
        .order_by(CatalogEmail.received_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "tenant_id": str(tenant_uuid),
        "accounts": [
            {
                "id": str(account.id),
                "email_address": account.email_address,
                "sync_status": account.sync_status,
                "sync_error_msg": account.sync_error_msg,
                "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
            }
            for account in accounts
        ],
        "sync_settings": {
            "ingestion_approach": sync_setting.ingestion_approach if sync_setting else None,
            "trusted_suppliers": sync_setting.trusted_suppliers if sync_setting else None,
            "pending_approval_count": len([item for item in pending_approvals if not item.get("ignored")]),
            "pending_approvals": pending_approvals[:limit],
        },
        "recent_emails": [
            {
                "id": str(email.id),
                "raw_email_id": email.raw_email_id,
                "supplier_name": supplier_name or email.sender_address or "Skipped email",
                "subject": email.subject,
                "received_at": email.received_at.isoformat() if email.received_at else None,
                "processing_status": email.processing_status,
                "item_count": int(item_count or 0),
                "visible_in_catalog": email.processing_status == "completed" and int(item_count or 0) > 0,
            }
            for email, supplier_name, item_count in email_rows
        ],
    }


@router.delete("/emails/{email_id}", status_code=204)
def delete_catalog_email(
    email_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a specific catalog email and all its extracted catalog items securely."""
    user_uuid = UUID(current_user["tenant_id"])
    email_record = db.query(CatalogEmail).filter(CatalogEmail.id == email_id, CatalogEmail.tenant_id == user_uuid).first()
    if not email_record:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail="Catalog email not found or access denied."
        )
    object_path = _storage_object_path_from_public_url(email_record.pdf_url)
    certificate_paths = [
        path
        for (raw_payload,) in db.query(CatalogItem.raw_payload).filter(
            CatalogItem.catalog_email_id == email_id,
            CatalogItem.tenant_id == user_uuid,
        )
        for path in certificate_storage_paths(raw_payload)
    ]
    try:
        db.query(CatalogItem).filter(
            CatalogItem.catalog_email_id == email_id,
            CatalogItem.tenant_id == user_uuid,
        ).delete(synchronize_session=False)
        # Keep a tombstone so future inbox syncs do not re-import a user-deleted email.
        email_record.processing_status = "deleted"
        email_record.pdf_url = None
        db.commit()
        background_tasks.add_task(delete_storage_object, object_path)
        for certificate_path in dict.fromkeys(certificate_paths):
            background_tasks.add_task(delete_storage_object, certificate_path)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while deleting the email record."
        )


@router.post("/upload-certificate", status_code=201)
async def upload_certificate(
    supplier_id: UUID,
    file: UploadFile = File(...),
    ingredient_name: str | None = Query(None),
    country_of_origin: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload a certificate file to Supabase Storage and attach to existing supplier item or create new table entry."""
    user_uuid = UUID(current_user["id"]) if isinstance(current_user.get("id"), str) else current_user["id"]
    active_tenant_id = current_user.get("tenant_id") or user_uuid
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.tenant_id == active_tenant_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")

    try:
        contents = await read_bounded_upload_file(file, max_bytes=MAX_CERTIFICATE_UPLOAD_BYTES)
    except ValueError as size_err:
        raise HTTPException(status_code=413, detail=str(size_err))

    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    raw_file_name = file.filename or "certificate.pdf"
    safe_name = sanitize_filename(raw_file_name, default_name="certificate.pdf")
    
    is_valid, canonical_mime, err_msg = validate_document_bytes(
        contents,
        safe_name,
        declared_mime=file.content_type,
        allowed_extensions=CERTIFICATE_ALLOWED_EXTENSIONS,
        max_bytes=MAX_CERTIFICATE_UPLOAD_BYTES,
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid certificate file: {err_msg}")

    file_name = safe_name
    object_path = f"certificates/{supplier_id}/{safe_name}"

    try:
        supabase = get_supabase()
        bucket = get_settings().supabase_storage_bucket
        ensure_supabase_storage_bucket(bucket)
        supabase.storage.from_(bucket).upload(
            object_path,
            contents,
            {"content-type": canonical_mime, "upsert": "true"},
        )
        public_url = supabase.storage.from_(bucket).get_public_url(object_path)
    except Exception as err:
        logger.error("Failed to upload certificate file to Supabase: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {err}")

    extracted_text = ""
    if file_name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
        try:
            if file_name.lower().endswith(".pdf"):
                from backend.app.services.pdf_extract import extract_pdf_document
                pdf_doc = extract_pdf_document(contents)
                extracted_text = pdf_doc.full_text
            else:
                from backend.app.services.ocr import recognize_image_to_text
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(contents))
                extracted_text = recognize_image_to_text(img, file_name)
        except Exception:
            pass

    from backend.app.services.document_classifier import _material_hint
    from backend.app.services.country_detection import detect_supplier_country, UNKNOWN_COUNTRY

    target_ingredient = clean_optional_text(ingredient_name) or _material_hint(file_name, extracted_text)
    if not target_ingredient:
        stem = re.sub(r"\.[A-Za-z0-9]+$", "", file_name)
        stem = re.sub(r"(?i)\b(?:certificate of analysis|certificate|cert|coa|analysis|report|pdf|scan|copy)\b", " ", stem)
        stem = re.sub(r"[_-]+", " ", stem).strip()
        target_ingredient = stem if len(stem) >= 3 else "Certificate Item"

    detected_country = clean_optional_text(country_of_origin) or detect_supplier_country(extracted_text, supplier.country)
    if detected_country == UNKNOWN_COUNTRY:
        detected_country = supplier.country or UNKNOWN_COUNTRY

    if detected_country != UNKNOWN_COUNTRY and getattr(supplier, "country", None) in {None, "", UNKNOWN_COUNTRY}:
        supplier.country = detected_country

    cert_obj = {
        "name": file_name,
        "url": public_url,
        "storage_path": object_path,
        "type": "Certificate",
    }

    existing_items = (
        db.query(CatalogItem)
        .filter(CatalogItem.supplier_id == supplier.id, CatalogItem.tenant_id == active_tenant_id)
        .all()
    )
    matched_item = None
    target_canonical = " ".join(re.sub(r"[^a-z0-9]+", " ", target_ingredient.lower()).split())
    for item in existing_items:
        item_canonical = " ".join(re.sub(r"[^a-z0-9]+", " ", item.ingredient_name.lower()).split())
        if target_canonical and (target_canonical in item_canonical or item_canonical in target_canonical):
            matched_item = item
            break

    if matched_item:
        raw_payload = dict(matched_item.raw_payload or {})
        cert_list = raw_payload.get("certificate_pdfs")
        if not isinstance(cert_list, list):
            cert_list = []
        if not any(isinstance(c, dict) and c.get("url") == public_url for c in cert_list):
            cert_list.append(cert_obj)
        raw_payload["certificate_pdfs"] = cert_list
        if detected_country != UNKNOWN_COUNTRY:
            raw_payload["country_of_origin"] = detected_country
        matched_item.raw_payload = raw_payload
        db.commit()
        db.refresh(matched_item)
        return {
            "message": "Certificate attached to existing item.",
            "item_id": str(matched_item.id),
            "ingredient_name": matched_item.ingredient_name,
            "certificate_url": public_url,
        }

    raw_payload = {
        "source": "certificate_document",
        "source_document": file_name,
        "specification": "Certificate",
        "country_of_origin": detected_country,
        "country": detected_country,
        "certificate_pdfs": [cert_obj],
    }
    certificate_email = CatalogEmail(
        id=uuid4(),
        tenant_id=active_tenant_id,
        supplier_id=supplier.id,
        raw_email_id=f"manual-certificate:{supplier.id}:{uuid4()}",
        subject=f"Manual certificate upload: {file_name}",
        pdf_url=public_url,
        body_preview=target_ingredient,
        processing_status="certificate",
    )
    db.add(certificate_email)
    new_item = CatalogItem(
        id=uuid4(),
        tenant_id=active_tenant_id,
        catalog_email_id=certificate_email.id,
        supplier_id=supplier.id,
        ingredient_name=target_ingredient,
        price_per_unit=None,
        currency="",
        available_qty=None,
        unit="kg",
        raw_payload=raw_payload,
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return {
        "message": "Created new item table entry for certificate.",
        "item_id": str(new_item.id),
        "ingredient_name": new_item.ingredient_name,
        "country_of_origin": detected_country,
        "certificate_url": public_url,
    }





import email
import email.utils
from collections import defaultdict
from email.header import decode_header
from html.parser import HTMLParser
import imaplib
import json
import logging
import re
import tempfile
import zipfile

from urllib.parse import unquote, urlparse
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any
from uuid import uuid4, UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import ensure_supabase_storage_bucket, get_supabase
from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.services.catalog_table_parser import (
    CATALOG_TABLE_PARSER_VERSION,
    _catalogue_header_has_required_shape,
    _header_cell_metadata,
    _header_map,
    extract_pack_size,
    is_valid_ingredient_name,
    parse_catalog_table_text,
)
from backend.app.services.country_detection import UNKNOWN_COUNTRY, detect_supplier_country
from backend.app.services.document_classifier import CATALOGUE, CERTIFICATE, DocumentClassification, classify_document
from backend.app.services.gmail_api import GmailApiClient
from backend.app.services.llm import OpenRouterClient
from backend.app.services.normalizer import normalize_item
from backend.app.services.pdf_extract import extract_pdf_text
from backend.app.schemas import ExtractedCatalogItem, clean_optional_text
from backend.app.security import validate_public_network_host
from backend.app.services.sanitizer import sanitize_preview_text
from backend.app.file_validator import (
    MAX_DATA_URI_BYTES,
    MAX_DATA_URI_COUNT,
    MAX_DOCUMENT_BYTES,
    MAX_TOTAL_DATA_URI_BYTES,
    MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES,
    sanitize_filename,
    validate_document_bytes,
)

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_COUNT = 10
IMAGE_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
CLASSIFIABLE_DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
MAX_EMAIL_RETRY_ATTEMPTS = 1

SUPPLIER_INTENT_TERMS = (
    "catalog",
    "catalogue",
    "price",
    "pricing",
    "quote",
    "quotation",
    "rfq",
    "offer",
    "coa",
    "certificate of analysis",
    "specification",
    "availability",
    "stock",
    "ingredient",
    "chemical",
    "api",
    "excipient",
    "raw material",
    "bulk",
)

CERTIFICATE_PDF_TERMS = (
    "certificate",
    "certificate of analysis",
    "coa",
    "c of a",
    "analysis certificate",
    "gmp",
    "cgmp",
    "fda",
    "iso",
    "halal",
    "kosher",
    "organic certificate",
    "organic",
    "lab report",
    "laboratory report",
    "test report",
    "quality report",
    "msds",
)

IRRELEVANT_MAIL_TERMS = (
    "unsubscribe",
    "newsletter",
    "webinar",
    "event",
    "promotion",
    "promotional",
    "marketing",
    "sale ends",
    "limited time",
    "digest",
    "no-reply",
    "noreply",
    "do-not-reply",
    "donotreply",
)


def get_supplier_domain(sender: str) -> str:
    if "@" not in sender:
        return sender.lower()
    return sender.strip().lower()


def trusted_sender_matches(sender: str | None, trusted_suppliers: str | None) -> bool:
    address = email.utils.parseaddr(sender or "")[1].strip().lower()
    if not address:
        address = str(sender or "").strip().lower()
    domain = address.rsplit("@", 1)[1] if "@" in address else address
    trusted_terms = {
        term.strip().lower()
        for term in str(trusted_suppliers or "").split(",")
        if term.strip()
    }
    return address in trusted_terms or domain in trusted_terms


def filter_trusted_pending_approvals(
    pending_approvals: str | None,
    trusted_suppliers: str | None,
) -> str:
    try:
        items = json.loads(pending_approvals or "[]")
    except (TypeError, ValueError):
        items = []
    if not isinstance(items, list):
        items = []
    filtered = [
        item
        for item in items
        if not (
            isinstance(item, dict)
            and trusted_sender_matches(str(item.get("sender") or ""), trusted_suppliers)
        )
    ]
    return json.dumps(filtered)


def public_processing_failure(error_message: str | None) -> str:
    message = str(error_message or "").lower()
    if "timeout" in message or "timed out" in message:
        return "processing timed out; please retry"
    if "attachment" in message or "document" in message or "file" in message:
        return "attachment could not be processed"
    return "email extraction could not be completed"


def _nullable_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "head", "meta", "title", "noscript"}:
            self._skip_depth += 1
        if tag.lower() in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "head", "meta", "title", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)

    def text(self) -> str:
        return "\n".join(self.parts)


class EmailIngestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.llm = OpenRouterClient(db=db)
        logger.info("MediCORE extraction engine ready: parser=%s", CATALOG_TABLE_PARSER_VERSION)

    def _extract_sender(self, message: Message) -> tuple[str, str]:
        from_header = message.get("From", "")
        try:
            decoded_parts = decode_header(from_header)
            decoded_from = []
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    decoded_from.append(part.decode(encoding or "utf-8", errors="ignore"))
                else:
                    decoded_from.append(part)
            from_header_str = "".join(decoded_from)
        except Exception:
            from_header_str = from_header

        sender_pair = email.utils.parseaddr(from_header_str)
        display_name = sender_pair[0]
        sender = sender_pair[1]

        # Clean up display name
        if display_name:
            display_name = display_name.strip().strip('"').strip("'").strip()
            display_name = " ".join(display_name.split())

        # Check body for forwarded sender pattern if display name is empty or matches email
        body_text = self._get_email_body_text(message)
        if (not display_name or display_name.lower() == sender.lower()) and body_text:
            import re
            body_match = re.search(r"(?mi)^\s*(?:from|From):\s*([^\n<]+)<([^>@]+@[^>]+)>", body_text)
            if body_match:
                body_name = body_match.group(1).strip().strip('"').strip("'").strip()
                body_email = body_match.group(2).strip()
                if body_name:
                    display_name = body_name
                    if "@" in body_email:
                        sender = body_email

        return display_name, sender

    def preview_imap_inbox(
        self,
        imap_username: str | None = None,
        imap_password: str | None = None,
        imap_mailbox: str | None = None,
    ) -> dict:
        using_supplied_credentials = bool(imap_username and imap_password)
        if self.settings.email_mode != "imap" and not using_supplied_credentials:
            return {"email_mode": self.settings.email_mode, "unread_count": 0, "pdf_messages": []}

        username = imap_username or self.settings.imap_username
        password = imap_password or self.settings.imap_password
        mailbox = imap_mailbox or self.settings.imap_mailbox

        with imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port, timeout=30) as client:
            client.login(username, password)
            client.select(mailbox)
            _, message_ids = client.uid("search", None, "UNSEEN")
            ids = message_ids[0].split() if message_ids and message_ids[0] else []
            pdf_messages = []
            for msg_id in ids:
                _, data = client.uid("fetch", msg_id, "(BODY.PEEK[])")
                if not data or not isinstance(data[0], tuple):
                    continue
                message = email.message_from_bytes(data[0][1])
                attachments = [att["filename"] for att in self._collect_attachments(message)]
                if attachments:
                    display_name, sender = self._extract_sender(message)
                    pdf_messages.append(
                        {
                            "raw_email_id": f"{username}:{mailbox}:{msg_id.decode()}",
                            "from": display_name or sender,
                            "email": sender,
                            "subject": message.get("Subject"),
                            "pdf_attachments": attachments,
                        }
                    )
            return {
                "email_mode": "imap" if using_supplied_credentials else self.settings.email_mode,
                "mailbox": mailbox,
                "unread_count": len(ids),
                "pdf_message_count": len(pdf_messages),
                "pdf_messages": pdf_messages,
            }

    def poll_imap_inbox(
        self,
        imap_username: str | None = None,
        imap_password: str | None = None,
        imap_mailbox: str | None = None,
    ) -> int:
        using_supplied_credentials = bool(imap_username and imap_password)
        if self.settings.email_mode != "imap" and not using_supplied_credentials:
            logger.info("Skipping IMAP poll because EMAIL_MODE=%s", self.settings.email_mode)
            return 0

        username = imap_username or self.settings.imap_username
        password = imap_password or self.settings.imap_password
        mailbox = imap_mailbox or self.settings.imap_mailbox

        processed = 0
        logger.info("Connecting to IMAP mailbox %s:%s/%s", self.settings.imap_host, self.settings.imap_port, mailbox)
        with imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port, timeout=30) as client:
            client.login(username, password)
            client.select(mailbox)
            _, message_ids = client.uid("search", None, "UNSEEN")
            ids = message_ids[0].split() if message_ids and message_ids[0] else []
            logger.info("Found %s unread IMAP message(s)", len(ids))
            for msg_id in ids:
                logger.info("Fetching IMAP message id=%s", msg_id.decode())
                _, data = client.uid("fetch", msg_id, "(RFC822)")
                if not data or not isinstance(data[0], tuple):
                    logger.info("Skipping IMAP message id=%s because it had no RFC822 payload", msg_id.decode())
                    continue
                message = email.message_from_bytes(data[0][1])
                processed += self._process_message(
                    message,
                    raw_email_id=f"{username}:{mailbox}:{msg_id.decode()}",
                )
        logger.info("IMAP poll completed; extracted %s catalogue item(s)", processed)
        return processed

    def process_gmail_push_payload(self, payload: dict) -> int:
        if not self.settings.gmail_oauth_token:
            return 0

        processed = 0
        gmail = GmailApiClient()
        for message_id, message in gmail.fetch_unread_pdf_messages():
            processed += self._process_message(message, raw_email_id=message_id)
        return processed

    def _process_message(
        self,
        message: Message,
        raw_email_id: str,
        parse_targets: list[dict] | None = None,
        tenant_id: Any | None = None,
        allow_logged_retry: bool = False,
    ) -> int:
        existing_status = self._existing_email_status(raw_email_id, tenant_id=tenant_id)
        if existing_status and not allow_logged_retry:
            logger.info("Skipping already-logged email id=%s status=%s", raw_email_id, existing_status)
            return 0
        if existing_status and not self._is_retryable_logged_email(existing_status):
            logger.info("Skipping non-retryable logged email id=%s status=%s", raw_email_id, existing_status)
            return 0

        display_name, sender = self._extract_sender(message)
        subject = clean_optional_text(message.get("Subject")) or "(no subject)"
        email_date = self._message_received_at(message)
        body_preview_text = self._get_email_body_text(message)

        country_contexts: list[str] = []
        if parse_targets is None:
            attachments = self._collect_attachments(message)
            body_text = body_preview_text
            if body_text:
                country_contexts.append(body_text)
            parse_targets = []
            for att in attachments:
                parse_targets.append({
                    "name": att["filename"],
                    "payload": att["payload"],
                    "ext": att["ext"],
                    "mime_type": att["mime_type"],
                    "is_body": False
                })
            if body_text.strip():
                parse_targets.append({
                    "name": "email_body.txt",
                    "payload": body_text.encode("utf-8"),
                    "ext": ".txt",
                    "mime_type": "text/plain",
                    "is_body": True
                })

        logger.info("Processing email id=%s from=%s subject=%r parse_targets=%s", raw_email_id, sender, subject, len(parse_targets))
        if not parse_targets:
            return 0

        supplier = self._upsert_supplier(sender, display_name=display_name, tenant_id=tenant_id)
        count = 0
        active_tenant_id = tenant_id or supplier.tenant_id
        catalog_email = (
            self.db.query(CatalogEmail)
            .filter(CatalogEmail.raw_email_id == raw_email_id)
            .filter(CatalogEmail.tenant_id == active_tenant_id)
            .first()
        )
        if catalog_email:
            logger.info("Reprocessing existing source email record id=%s", raw_email_id)
            self.db.query(CatalogItem).filter(CatalogItem.catalog_email_id == catalog_email.id).delete(
                synchronize_session=False
            )
            catalog_email.processing_status = "processing"
            catalog_email.subject = subject
            catalog_email.received_at = email_date
            catalog_email.pdf_url = None
            catalog_email.body_preview = self._body_preview(body_preview_text)
            catalog_email.duplicate_count = 0
        else:
            catalog_email = CatalogEmail(
                id=uuid4(),
                tenant_id=active_tenant_id,
                supplier_id=supplier.id,
                raw_email_id=raw_email_id,
                subject=subject,
                pdf_url=None,
                body_preview=self._body_preview(body_preview_text),
                received_at=email_date,
                processing_status="processing",
                duplicate_count=0,
            )
            self.db.add(catalog_email)
        self.db.flush()

        uploaded_object_paths: list[str] = []
        certificate_refs: list[dict[str, str]] = []
        processing_errors: list[str] = []
        extracted_text_parts: list[str] = []
        for target in parse_targets:
            target_name = str(target["name"]).replace("\\", "/").split("/")[-1].strip()
            if not target_name:
                target_name = "email_payload.txt" if target.get("is_body") else f"attachment-{uuid4()}"
            payload = target["payload"]
            ext = target["ext"]
            mime_type = target["mime_type"]
            if len(payload) > MAX_DOCUMENT_BYTES:
                logger.warning("Skipping %s because it exceeds the 30 MB processing limit", target_name)
                processing_errors.append(f"{target_name}: file exceeds 30 MB")
                continue

            logger.info("Processing target %s (%s bytes)", target_name, len(payload))
            from backend.app.services.terminal_sync_status import sync_notifier
            sync_notifier.notify_pdf_found(target_name, len(payload) / 1024.0)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
                try:
                    file_path = Path(tmp_dir) / target_name
                    file_path.write_bytes(payload)
                    uploaded_url, object_path = self._upload_file(file_path, raw_email_id, mime_type)

                    if ext in IMAGE_ATTACHMENT_EXTENSIONS:
                        image_items = self._extract_catalogue_items_from_image(file_path, tenant_id=active_tenant_id)
                        if image_items:
                            logger.info(
                                "Image catalogue vision returned %s validated item(s); bypassing parser/LLM for %s",
                                len(image_items),
                                target_name,
                            )
                            uploaded_object_paths.append(object_path)
                            if not catalog_email.pdf_url:
                                catalog_email.pdf_url = uploaded_url
                            image_text = self._catalogue_item_evidence_text(image_items)
                            count += self._store_catalog_items(
                                catalog_email,
                                supplier,
                                image_items,
                                image_text,
                                tenant_id=tenant_id,
                                source_name=target_name,
                            )
                            continue
                        logger.info(
                            "Image catalogue vision returned no valid items for %s; falling back to text parser",
                            target_name,
                        )

                    try:
                        text = self._extract_text_from_file(file_path, ext, tenant_id=active_tenant_id)
                    except Exception as text_exc:
                        text = ""
                        logger.warning("Failed extracting text from %s: %s", target_name, text_exc, exc_info=True)
                        if not self._is_certificate_pdf(target_name, ext, ""):
                            raise
                    logger.info("Extracted %s characters of text from %s", len(text), target_name)
                    if text:
                        country_contexts.append(text)
                        extracted_text_parts.append(text)
                    email_context = f"{catalog_email.subject or ''}\n{catalog_email.body_preview or ''}"
                    if ext in CLASSIFIABLE_DOCUMENT_EXTENSIONS:
                        classification = self._classify_document(target_name, ext, text, context_text=email_context)
                        logger.info(
                            "Classified document %s as %s confidence=%.2f",
                            target_name,
                            classification.category,
                            classification.confidence,
                        )

                        if classification.category == CERTIFICATE:
                            certificate_refs.append(
                                {
                                    "name": target_name,
                                    "url": uploaded_url,
                                    "storage_path": object_path,
                                    "type": self._certificate_type(target_name, text),
                                    "match_text": text[:10000],
                                    "material_hint": classification.material_hint or "",
                                }
                            )
                            logger.info("Stored certificate document %s for email id=%s", target_name, raw_email_id)
                            continue

                        if classification.category != CATALOGUE:
                            uploaded_object_paths.append(object_path)
                            logger.info("Skipping non-catalogue document %s after classification", target_name)
                            continue

                        text = self._extract_catalogue_text_from_file(file_path, ext, text, tenant_id=active_tenant_id)
                        logger.info("Catalogue extraction text for %s has %s characters", target_name, len(text))
                    else:
                        logger.info("Skipping document classifier for non-PDF attachment %s", target_name)
                    uploaded_object_paths.append(object_path)
                    if not catalog_email.pdf_url:
                        catalog_email.pdf_url = uploaded_url

                    extracted = self._extract_items_from_text(
                        text,
                        target_name,
                        reference_date=catalog_email.received_at,
                        tenant_id=active_tenant_id,
                    )
                    count += self._store_catalog_items(
                        catalog_email,
                        supplier,
                        extracted,
                        text,
                        tenant_id=tenant_id,
                        source_name=target_name,
                    )
                except Exception as exc:
                    logger.exception("Failed processing target %s for email id=%s", target_name, raw_email_id)
                    processing_errors.append(f"{target_name}: {exc}")
        # If no target produced catalogue rows, fall back to the combined body
        # text. Certificate replies may still carry negotiation updates such as
        # "Price: USD22.7/kg" that should update the prior thread item.
        if count == 0 and not processing_errors:
            combined_body = "\n".join(filter(None, [body_preview_text, *extracted_text_parts]))
            if combined_body.strip():
                if self._commercial_updates_from_text(combined_body):
                    count += self._apply_thread_reply_update(
                        catalog_email,
                        supplier,
                        combined_body,
                        active_tenant_id,
                    )

                extracted_from_body = []
                if count == 0 and not certificate_refs:
                    extracted_from_body = self._extract_items_from_text(
                        combined_body,
                        "email_body",
                        reference_date=catalog_email.received_at,
                        tenant_id=active_tenant_id,
                    )
                    if extracted_from_body:
                        count += self._store_catalog_items(
                            catalog_email,
                            supplier,
                            extracted_from_body,
                            combined_body,
                            tenant_id=tenant_id,
                            source_name="email_body",
                        )
                if count == 0 and not self._commercial_updates_from_text(combined_body):
                    count += self._apply_thread_reply_update(
                        catalog_email,
                        supplier,
                        combined_body,
                        active_tenant_id,
                    )
        self._update_supplier_country(supplier, *country_contexts)
        if certificate_refs:
            self.db.flush()
            self._attach_certificate_refs(catalog_email, supplier, certificate_refs)
        if count > 0:
            catalog_email.processing_status = "partial" if processing_errors else "completed"
            self._touch_supplier_last_email(supplier, catalog_email.received_at)
            self._delete_uploaded_files(uploaded_object_paths)
            catalog_email.pdf_url = None
        elif certificate_refs and not processing_errors:
            catalog_email.processing_status = "certificate"
            self._touch_supplier_last_email(supplier, catalog_email.received_at)
            self._delete_uploaded_files(uploaded_object_paths)
        else:
            self._delete_uploaded_files(uploaded_object_paths)
            if processing_errors:
                catalog_email.processing_status = "failed"
            else:
                catalog_email.processing_status = "skipped"
            logger.warning("No catalogue rows were stored for email id=%s", raw_email_id)
        self.db.commit()
        logger.info("Committed %s catalogue item(s) for email id=%s", count, raw_email_id)
        return count

    def _fetch_reprocess_bytes(self, pdf_ref: str) -> bytes | None:
        """Securely fetch attachment bytes from Supabase storage, preventing SSRF."""
        bucket = self.settings.supabase_storage_bucket
        supabase = get_supabase()

        # Direct storage object path
        if not pdf_ref.startswith(("http://", "https://")):
            clean_path = pdf_ref.strip().lstrip("/")
            try:
                return supabase.storage.from_(bucket).download(clean_path)
            except Exception as err:
                logger.warning("Failed downloading storage path %s: %s", clean_path, err)
                return None

        # Public or signed URL: validate host matches configured Supabase host
        parsed = urlparse(pdf_ref)
        configured_supabase = urlparse(self.settings.supabase_url)

        if parsed.hostname != configured_supabase.hostname:
            logger.warning("Rejecting reprocess URL %s: host does not match configured Supabase storage host %s", pdf_ref, configured_supabase.hostname)
            return None

        # Extract bucket object path from URL
        public_marker = f"/storage/v1/object/public/{bucket}/"
        sign_marker = f"/storage/v1/object/sign/{bucket}/"
        object_path = None
        if public_marker in parsed.path:
            object_path = unquote(parsed.path.split(public_marker, 1)[1])
        elif sign_marker in parsed.path:
            object_path = unquote(parsed.path.split(sign_marker, 1)[1])

        if not object_path:
            logger.warning("Rejecting reprocess URL %s: does not target configured bucket %s", pdf_ref, bucket)
            return None

        try:
            return supabase.storage.from_(bucket).download(object_path)
        except Exception as err:
            logger.warning("Failed downloading validated Supabase object %s: %s", object_path, err)
            return None

    def reprocess_empty_catalog_emails(
        self,
        limit: int = 25,
        force: bool = False,
        tenant_id: Any | None = None,
    ) -> int:
        tenant_uuid = UUID(str(tenant_id)) if tenant_id is not None else None
        if force:
            query = self.db.query(CatalogEmail).filter(CatalogEmail.pdf_url.isnot(None))
        else:
            query = (
                self.db.query(CatalogEmail)
                .outerjoin(CatalogItem, CatalogItem.catalog_email_id == CatalogEmail.id)
                .filter(CatalogItem.id.is_(None), CatalogEmail.pdf_url.isnot(None))
            )
        if tenant_uuid is not None:
            query = query.filter(CatalogEmail.tenant_id == tenant_uuid)
        empty_emails = query.order_by(CatalogEmail.received_at.desc()).limit(limit).all()

        processed = 0
        for catalog_email in empty_emails:
            if not catalog_email.pdf_url:
                continue
            supplier = (
                self.db.query(Supplier)
                .filter(
                    Supplier.id == catalog_email.supplier_id,
                    Supplier.tenant_id == catalog_email.tenant_id,
                )
                .first()
            )
            if not supplier:
                continue
            logger.info("Reprocessing stored attachment for email id=%s", catalog_email.raw_email_id)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
                attachment_name = catalog_email.raw_email_id.split(":")[-1]
                ext = Path(attachment_name.lower()).suffix if ":" in catalog_email.raw_email_id else ".pdf"
                if not ext:
                    ext = ".pdf"
                file_path = Path(tmp_dir) / f"{catalog_email.id}{ext}"
                
                content = self._fetch_reprocess_bytes(catalog_email.pdf_url)
                if not content:
                    logger.warning("Skipping reprocess for %s: unable to securely retrieve stored content", catalog_email.raw_email_id)
                    continue
                if len(content) > MAX_DOCUMENT_BYTES:
                    logger.warning("Skipping reprocess for %s because stored file exceeds 30 MB", catalog_email.raw_email_id)
                    continue
                file_path.write_bytes(content)
                catalog_email.processing_status = "processing"
                catalog_email.duplicate_count = 0
                if force:
                    self.db.query(CatalogItem).filter(
                        CatalogItem.catalog_email_id == catalog_email.id,
                        CatalogItem.tenant_id == catalog_email.tenant_id,
                    ).delete(synchronize_session=False)

                if ext in IMAGE_ATTACHMENT_EXTENSIONS:
                    image_items = self._extract_catalogue_items_from_image(file_path, tenant_id=catalog_email.tenant_id)
                    if image_items:
                        image_text = self._catalogue_item_evidence_text(image_items)
                        stored = self._store_catalog_items(catalog_email, supplier, image_items, image_text, tenant_id=catalog_email.tenant_id)
                        processed += stored
                        if stored > 0:
                            catalog_email.processing_status = "completed"
                            self._touch_supplier_last_email(supplier, catalog_email.received_at)
                        else:
                            catalog_email.processing_status = "skipped"
                        continue
                    logger.info(
                        "Image catalogue vision returned no valid items for reprocess %s; falling back to text parser",
                        catalog_email.raw_email_id,
                    )

                text = self._extract_text_from_file(file_path, ext, tenant_id=catalog_email.tenant_id)
                logger.info("Extracted %s characters while reprocessing email id=%s", len(text), catalog_email.raw_email_id)
                if ext in CLASSIFIABLE_DOCUMENT_EXTENSIONS:
                    classification = self._classify_document(file_path.name, ext, text)
                    if classification.category != CATALOGUE:
                        catalog_email.processing_status = classification.category
                        logger.info(
                            "Skipping reprocess catalogue extraction for %s because document classified as %s",
                            catalog_email.raw_email_id,
                            classification.category,
                        )
                        continue
                    text = self._extract_catalogue_text_from_file(file_path, ext, text, tenant_id=catalog_email.tenant_id)
                    logger.info("Catalogue reprocess text for email id=%s has %s characters", catalog_email.raw_email_id, len(text))
                else:
                    logger.info("Skipping document classifier for non-PDF reprocess %s", catalog_email.raw_email_id)
                extracted = self._extract_items_from_text(
                    text,
                    str(catalog_email.id),
                    reference_date=catalog_email.received_at,
                    tenant_id=catalog_email.tenant_id,
                )
                stored = self._store_catalog_items(catalog_email, supplier, extracted, text, tenant_id=catalog_email.tenant_id)
                processed += stored
                if stored > 0:
                    catalog_email.processing_status = "completed"
                    self._touch_supplier_last_email(supplier, catalog_email.received_at)
                else:
                    catalog_email.processing_status = "skipped"
        self.db.commit()
        logger.info("Reprocessed %s catalogue item(s) from stored attachments", processed)
        return processed

    def reprocess_stored_attachments(
        self,
        limit: int = 25,
        force: bool = False,
        tenant_id: Any | None = None,
    ) -> int:
        return self.reprocess_empty_catalog_emails(limit=limit, force=force, tenant_id=tenant_id)

    def _extract_items_from_text(
        self,
        text: str,
        source_name: str,
        reference_date: datetime | None = None,
        tenant_id: Any | None = None,
    ):
        if not text.strip():
            logger.info("No text available for %s", source_name)
            return []

        parser_text = self._preferred_parser_text(text)
        parsed = [
            normalize_item(item)
            for item in parse_catalog_table_text(
                parser_text,
                reference_date=reference_date,
                # Spreadsheet catalogues can legitimately contain repeated
                # rows across sheets/regions. Keep them through parsing; DB
                # insertion still skips exact unchanged duplicates safely.
                dedupe=not self._is_spreadsheet_table_text(parser_text),
            )
        ]
        if not self._is_spreadsheet_table_text(parser_text):
            parsed = self._dedupe_extracted_items(parsed)
        source_lower = source_name.lower()
        conversational_source = source_lower.endswith(".txt") or "email_body" in source_lower
        logger.info("Deterministic table parser extracted %s catalogue row(s) from %s", len(parsed), source_name)

        if len(parsed) >= (1 if conversational_source else 20):
            logger.info(
                "Using %s deterministic parser row(s) for catalogue %s; skipping LLM fallback",
                len(parsed),
                source_name,
            )
            return parsed

        if (
            ("[EXCEL TABLE]" in text or "[CSV TABLE]" in text or "[RAPIDOCR TABLE OCR]" in text)
            or (not conversational_source and self._looks_like_structured_table_text(parser_text))
        ) and parsed:
            logger.info(
                "Using %s deterministic structured table parser row(s) for catalogue %s; skipping LLM fallback",
                len(parsed),
                source_name,
            )
            return parsed

        if not getattr(self, "llm", None):
            return parsed

        try:
            try:
                raw_llm_items = self.llm.extract_catalog_items(
                    text,
                    reference_date=reference_date,
                    tenant_id=tenant_id,
                )
            except TypeError as exc:
                if "tenant_id" not in str(exc):
                    raise
                raw_llm_items = self.llm.extract_catalog_items(
                    text,
                    reference_date=reference_date,
                )
            llm_items = [
                normalize_item(item)
                for item in raw_llm_items
            ]
            extracted = self._dedupe_extracted_items([*parsed, *llm_items])
            logger.info("LLM fallback extracted %s catalogue row(s) from %s", len(extracted), source_name)
            return extracted
        except Exception:
            logger.exception("LLM extraction failed for %s", source_name)
            return parsed

    def _preferred_parser_text(self, text: str) -> str:
        table_blocks: list[str] = []
        for marker in ("[RAPIDOCR TABLE OCR]\n", "[GRID CELL TABLE OCR]\n", "[PDF INSPECTOR MARKDOWN]\n", "[PDF NATIVE TABLE]\n"):
            if marker in text:
                for part in text.split(marker)[1:]:
                    block = part.split("\n\n", 1)[0].strip()
                    if block:
                        table_blocks.append(block)
        return "\n\n".join(dict.fromkeys(table_blocks)) or text

    def _is_spreadsheet_table_text(self, text: str) -> bool:
        return "[XLSX TABLE]" in text or "[CSV TABLE]" in text

    def _looks_like_structured_table_text(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        table_rows = 0
        separator_rows = 0
        header_rows = 0
        for line in lines[:200]:
            if "|" not in line:
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 3:
                continue
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells if cell):
                separator_rows += 1
                continue
            table_rows += 1
            header = " ".join(cells).lower()
            if any(term in header for term in ("product", "ingredient", "material", "price", "fob", "qty", "quantity")):
                header_rows += 1
        if separator_rows >= 1:
            return table_rows >= 2
        return table_rows >= 3 and header_rows >= 1 and table_rows / max(len(lines), 1) >= 0.8

    def _dedupe_extracted_items(self, items) -> list:
        deduped = []
        seen: set[tuple] = set()
        for item in items:
            key = (
                item.ingredient_name.strip().lower(),
                self._item_specification(item),
                str(item.price_per_unit),
                (item.currency or "").upper(),
                str(item.available_qty) if item.available_qty is not None else None,
                (item.unit or "").strip().lower(),
                item.lead_time_text or item.lead_time_days,
                str(item.moq) if item.moq is not None else None,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _store_catalog_items(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        items,
        text: str,
        tenant_id: Any | None = None,
        source_name: str | None = None,
    ) -> int:
        count = 0
        duplicate_count = 0
        active_tenant_id = tenant_id or supplier.tenant_id
        prepared_items = []
        seen_in_document: set[tuple] = set()
        for item in items:
            item = self._with_source_note(item, text)
            item = self._remove_unsupported_price(item, text)
            if not self._has_valid_ingredient_name(item):
                logger.warning(
                    "Skipping extracted item with invalid ingredient name: %s",
                    item.model_dump(mode="json"),
                )
                continue
            if not self._has_required_grounded_values(item):
                logger.warning(
                    "Skipping extracted item with missing required grounded values: %s",
                    item.model_dump(mode="json"),
                )
                continue
            identity_key = self._item_identity_key(item)
            value_key = (
                identity_key,
                str(item.price_per_unit),
                (item.currency or "").upper(),
                str(item.available_qty) if item.available_qty is not None else None,
                (item.unit or "").strip().lower(),
                item.lead_time_text or item.lead_time_days,
                str(item.moq) if item.moq is not None else None,
            )
            if value_key in seen_in_document:
                duplicate_count += 1
                continue
            seen_in_document.add(value_key)
            prepared_items.append(item)

        existing_by_identity = self._existing_supplier_items_by_identity(
            catalog_email,
            supplier,
            prepared_items,
            active_tenant_id,
        )

        for item in prepared_items:
            existing_candidates = existing_by_identity.get(self._item_identity_key(item), [])
            existing_item = existing_candidates[0] if existing_candidates else None
            has_changed = True
            if existing_candidates:
                has_changed = self._catalog_item_values_changed(existing_candidates[0], item)

            if not has_changed:
                duplicate_count += 1
                logger.info(
                    "Skipping unchanged catalogue item supplier=%s item=%s",
                    supplier.email_domain,
                    item.ingredient_name,
                )
                continue

            raw_payload = self._compact_payload(item.model_dump(mode="json"))
            raw_payload["source"] = "email_extracted_catalogue"
            if clean_optional_text(source_name):
                raw_payload["source_document"] = clean_optional_text(source_name)
            pack_size = clean_optional_text(self._pack_size_for_item(text, item.ingredient_name))
            if pack_size:
                raw_payload["pack_size"] = pack_size
            raw_payload.update(self._compact_payload(self._notes_payload(item.notes)))
            raw_payload.update(self._compact_payload(self._exact_display_payload(item, text)))
            corrections = self._corrections_from_notes(item.notes)
            if corrections:
                raw_payload["corrections"] = corrections
            if item.price_per_unit is not None and not clean_optional_text(item.currency):
                raw_payload["currency_not_stated"] = True
            
            # MOQ and packing are the same thing: sync item.moq and raw_payload["pack_size"]
            if item.moq is None:
                pkg_val = raw_payload.get("pack_size") or raw_payload.get("packaging")
                if pkg_val:
                    num_match = re.search(r"(\d+(?:\.\d+)?)", str(pkg_val))
                    if num_match:
                        try:
                            item.moq = float(num_match.group(1))
                            raw_payload["moq"] = item.moq
                        except ValueError:
                            pass
            elif not raw_payload.get("pack_size"):
                raw_payload["pack_size"] = f"{item.moq:g} {item.unit or ''}".strip()
            if existing_item:
                logger.info(
                    "Updating existing catalogue item supplier=%s item=%s from email id=%s",
                    supplier.email_domain,
                    item.ingredient_name,
                    catalog_email.raw_email_id,
                )
                merged_payload = dict(existing_item.raw_payload or {})
                merged_payload.update(raw_payload)
                merged_payload["is_updated"] = True
                merged_payload["updated_from_catalog_email_id"] = str(catalog_email.id)
                merged_payload["updated_received_at"] = catalog_email.received_at.isoformat() if catalog_email.received_at else None
                existing_item.catalog_email_id = catalog_email.id
                existing_item.ingredient_name = item.ingredient_name
                if item.price_per_unit is not None:
                    existing_item.price_per_unit = item.price_per_unit
                    existing_item.currency = item.currency
                elif clean_optional_text(item.currency):
                    existing_item.currency = item.currency
                if item.available_qty is not None:
                    existing_item.available_qty = item.available_qty
                if clean_optional_text(item.unit):
                    existing_item.unit = item.unit
                if item.valid_until is not None:
                    existing_item.valid_until = item.valid_until
                if item.lead_time_days is not None:
                    existing_item.lead_time_days = item.lead_time_days
                if item.moq is not None:
                    existing_item.moq = item.moq
                existing_item.raw_payload = merged_payload
            else:
                self.db.add(
                    CatalogItem(
                        id=uuid4(),
                        tenant_id=active_tenant_id,
                        catalog_email_id=catalog_email.id,
                        supplier_id=supplier.id,
                        ingredient_name=item.ingredient_name,
                        price_per_unit=item.price_per_unit,
                        currency=item.currency,
                        available_qty=item.available_qty,
                        unit=item.unit,
                        valid_until=item.valid_until,
                        lead_time_days=item.lead_time_days,
                        moq=item.moq,
                        raw_payload=raw_payload,
                    )
                )
            count += 1
        catalog_email.duplicate_count = int(catalog_email.duplicate_count or 0) + duplicate_count
        return count

    def _with_source_note(self, item, text: str):
        notes = item.notes or ""
        if "source=" in notes.lower() or "source:" in notes.lower():
            return item

        ingredient = (item.ingredient_name or "").lower().strip()
        raw_source_phrase = (getattr(item, "raw_payload", None) or {}).get("source_phrase", "").lower().strip()

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for raw_line in lines:
            normalized_line = " ".join(raw_line.split())
            line_lower = normalized_line.lower()
            line_canonical = " ".join(re.sub(r"[^a-z0-9]+", " ", line_lower).split())
            ing_canonical = " ".join(re.sub(r"[^a-z0-9]+", " ", ingredient).split())

            matched = (ingredient and ingredient in line_lower) or (ing_canonical and ing_canonical in line_canonical)
            if not matched and raw_source_phrase:
                matched = raw_source_phrase in line_lower
            if not matched and ing_canonical:
                tokens = [t for t in ing_canonical.split() if len(t) >= 4]
                if tokens:
                    matched = any(t in line_canonical for t in tokens)

            if matched:
                if item.price_per_unit is None or self._price_appears_in_line(item.price_per_unit, normalized_line):
                    safe_line = normalized_line[:500].replace("'", "")
                    joined_notes = f"{notes}; source='{safe_line}'" if notes else f"source='{safe_line}'"
                    return item.model_copy(update={"notes": joined_notes})

        if "[RAPIDOCR TABLE OCR]" in text or "[EXCEL TABLE]" in text or "[CSV TABLE]" in text or "[PDF INSPECTOR MARKDOWN]" in text or "[GRID CELL TABLE OCR]" in text:
            safe_line = lines[0][:500].replace("'", "") if lines else "structured_table_row"
            joined_notes = f"{notes}; source='{safe_line}'" if notes else f"source='{safe_line}'"
            return item.model_copy(update={"notes": joined_notes})

        return item

    def _price_appears_in_line(self, value: Any, line: str) -> bool:
        try:
            number = float(value)
        except Exception:
            return False

        compact_line = line.replace(",", "")
        variants = {
            str(int(number)) if number.is_integer() else f"{number:g}",
            f"{number:.2f}",
            f"{number:.4f}".rstrip("0").rstrip("."),
        }
        return any(variant in compact_line for variant in variants if variant)

    def _remove_unsupported_price(self, item, text: str):
        if item.price_per_unit is None or self._item_has_price_evidence(item, text):
            return item
        logger.info(
            "Clearing unsupported price for item %s because source evidence has quantity/volume but no price signal",
            item.ingredient_name,
        )
        return item.model_copy(update={"price_per_unit": None, "currency": ""})

    def _item_has_price_evidence(self, item, text: str) -> bool:
        notes_payload = self._notes_payload(item.notes)
        evidence = " ".join(
            filter(
                None,
                [
                    notes_payload.get("original_price"),
                    notes_payload.get("price_display"),
                    notes_payload.get("source"),
                    item.notes or "",
                ],
            )
        )
        if self._text_has_price_signal(evidence):
            return True

        ingredient = self._canonical_match_text(item.ingredient_name)
        for line in text.splitlines():
            canonical_line = self._canonical_match_text(line)
            if ingredient and ingredient in canonical_line and self._text_has_price_signal(line):
                return True
        return False

    def _text_has_price_signal(self, value: str | None) -> bool:
        if not value:
            return False
        return bool(
            re.search(
                r"(?:price|rate|quote|cost|fob|cif|exw|cnf|c&f|ddp|dap|"
                r"US\$|\$|USD|INR|Rs\.?|₹|EUR|€|GBP|£|CAD|AUD|SGD|CHF|AED|CNY|JPY|/\s*(?:kg|g|mg|ml|l|unit|pack|bag|drum|mt|ton))",
                value,
                flags=re.IGNORECASE,
            )
        )

    def _has_required_grounded_values(self, item) -> bool:
        if not clean_optional_text(getattr(item, "ingredient_name", None)):
            return False
        if item.price_per_unit is not None and float(item.price_per_unit) <= 0:
            return False
        if item.available_qty is not None and float(item.available_qty) < 0:
            return False
        if (
            item.price_per_unit is None
            and item.available_qty is None
            and item.moq is None
            and not clean_optional_text(getattr(item, "specification", None))
            and not clean_optional_text(self._notes_payload(getattr(item, "notes", None)).get("specification"))
        ):
            return False
        notes = (item.notes or "").lower()
        # Every stored item must be traceable to an exact line in the source
        # email/attachment.  Commercial fields alone are not evidence: an LLM
        # may infer them from an address or a table heading.
        return "source=" in notes or "source:" in notes

    def _has_valid_ingredient_name(self, item) -> bool:
        return is_valid_ingredient_name(getattr(item, "ingredient_name", None))

    def _existing_supplier_items_by_identity(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        items,
        tenant_id: Any,
    ) -> dict[tuple, list[CatalogItem]]:
        ingredient_names = {
            item.ingredient_name.strip().lower()
            for item in items
            if clean_optional_text(item.ingredient_name)
        }
        if not ingredient_names:
            return {}

        previous_items = (
            self.db.query(CatalogItem)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .filter(
                CatalogItem.tenant_id == tenant_id,
                CatalogItem.supplier_id == supplier.id,
                func.lower(CatalogItem.ingredient_name).in_(ingredient_names),
                CatalogItem.catalog_email_id != catalog_email.id,
            )
            .order_by(CatalogEmail.received_at.desc(), CatalogItem.id.desc())
            .all()
        )
        grouped: dict[tuple, list[CatalogItem]] = defaultdict(list)
        for previous in previous_items:
            grouped[self._item_identity_key(previous)].append(previous)
        return dict(grouped)

    def _catalog_item_values_changed(self, previous: CatalogItem, item) -> bool:
        return any(
            [
                _nullable_float(previous.price_per_unit) != _nullable_float(item.price_per_unit),
                (previous.currency or "").upper() != (item.currency or "").upper(),
                _nullable_float(previous.available_qty) != _nullable_float(item.available_qty),
                (previous.unit or "").strip().lower() != (item.unit or "").strip().lower(),
                _nullable_float(previous.moq) != _nullable_float(item.moq),
                (previous.lead_time_days or None) != (item.lead_time_days or None),
                (previous.raw_payload or {}).get("lead_time_text") != (item.lead_time_text or None),
                self._item_specification(previous) != self._item_specification(item),
            ]
        )

    def _apply_thread_reply_update(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        text: str,
        tenant_id: Any,
    ) -> int:
        updates = self._commercial_updates_from_text(text)
        if not updates:
            return 0

        previous_item = self._thread_reply_update_candidate(catalog_email, supplier, text, tenant_id)
        if previous_item is None:
            logger.info("Skipping thread reply update for email id=%s because no safe prior item match was found", catalog_email.raw_email_id)
            return 0

        changed = False
        if updates.get("price_per_unit") is not None and _nullable_float(previous_item.price_per_unit) != _nullable_float(updates["price_per_unit"]):
            previous_item.price_per_unit = updates["price_per_unit"]
            previous_item.currency = updates.get("currency") or previous_item.currency
            changed = True
        if updates.get("moq") is not None and _nullable_float(previous_item.moq) != _nullable_float(updates["moq"]):
            previous_item.moq = updates["moq"]
            changed = True
        if updates.get("lead_time_days") is not None and (previous_item.lead_time_days or None) != updates["lead_time_days"]:
            previous_item.lead_time_days = updates["lead_time_days"]
            changed = True

        if not changed:
            return 0

        raw_payload = dict(previous_item.raw_payload or {})
        raw_payload.update(self._compact_payload(updates))
        raw_payload["is_updated"] = True
        raw_payload["conversation_update"] = True
        raw_payload["updated_from_catalog_email_id"] = str(catalog_email.id)
        raw_payload["updated_received_at"] = catalog_email.received_at.isoformat() if catalog_email.received_at else None
        previous_item.raw_payload = raw_payload
        previous_item.catalog_email_id = catalog_email.id
        logger.info(
            "Applied thread reply update supplier=%s item=%s email id=%s",
            supplier.email_domain,
            previous_item.ingredient_name,
            catalog_email.raw_email_id,
        )
        return 1

    def _commercial_updates_from_text(self, text: str) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        currency_pattern = r"(?:US\$|A\$|C\$|S\$|\$|USD|INR|Rs\.?|₹|EUR|€|GBP|£|CAD|AUD|SGD|CHF|AED|CNY|JPY|KRW|¥|₩)"
        price_match = re.search(
            rf"(?i)(?:updated\s+price|revised\s+price|new\s+price|price)\s*[:\-]?\s*({currency_pattern})?\s*([0-9][0-9,]*(?:\.\d+)?)",
            text,
        )
        if price_match:
            currency_token = (price_match.group(1) or "").upper()
            currency = (
                "USD" if currency_token in {"$", "US$"}
                else "INR" if currency_token in {"RS", "RS.", "₹"}
                else "EUR" if currency_token == "€"
                else "GBP" if currency_token == "£"
                else "AUD" if currency_token == "A$"
                else "CAD" if currency_token == "C$"
                else "SGD" if currency_token == "S$"
                else "CNY" if currency_token == "¥"
                else "KRW" if currency_token == "₩"
                else currency_token
            )
            updates["price_per_unit"] = float(price_match.group(2).replace(",", ""))
            updates["currency"] = currency or ""

        moq_match = re.search(r"(?i)\bMOQ\b\s*[:\-]?\s*([0-9][0-9,]*(?:\.\d+)?)", text)
        if moq_match:
            updates["moq"] = float(moq_match.group(1).replace(",", ""))

        lead_match = re.search(r"(?i)(?:lead\s*time|delivery)\s*[:\-]?\s*([0-9]{1,3})\s*(?:days?|d)\b", text)
        if lead_match:
            updates["lead_time_days"] = int(lead_match.group(1))
            updates["lead_time_text"] = f"{lead_match.group(1)} days"

        return updates

    def _thread_reply_update_candidate(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        text: str,
        tenant_id: Any,
    ) -> CatalogItem | None:
        normalized_subject = self._conversation_subject_key(catalog_email.subject or "")
        same_subject_items = []
        if normalized_subject:
            previous_emails = (
                self.db.query(CatalogEmail.id, CatalogEmail.subject)
                .filter(
                    CatalogEmail.tenant_id == tenant_id,
                    CatalogEmail.supplier_id == supplier.id,
                    CatalogEmail.id != catalog_email.id,
                )
                .order_by(CatalogEmail.received_at.desc())
                .limit(25)
                .all()
            )
            same_subject_email_ids = {
                email_id
                for email_id, subject in previous_emails
                if self._conversation_subject_key(subject or "") == normalized_subject
            }
            if same_subject_email_ids:
                same_subject_items = (
                    self.db.query(CatalogItem)
                    .filter(
                        CatalogItem.tenant_id == tenant_id,
                        CatalogItem.supplier_id == supplier.id,
                        CatalogItem.catalog_email_id.in_(same_subject_email_ids),
                    )
                    .order_by(CatalogItem.id.desc())
                    .all()
                )

        explicit_mentions = [
            item
            for item in same_subject_items
            if self._text_mentions_item(text, item)
        ]
        if len(explicit_mentions) == 1:
            return explicit_mentions[0]
        if len(same_subject_items) == 1:
            return same_subject_items[0]

        supplier_items = (
            self.db.query(CatalogItem)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .filter(
                CatalogItem.tenant_id == tenant_id,
                CatalogItem.supplier_id == supplier.id,
                CatalogItem.catalog_email_id != catalog_email.id,
            )
            .order_by(CatalogEmail.received_at.desc(), CatalogItem.id.desc())
            .limit(50)
            .all()
        )
        mentioned_items = [item for item in supplier_items if self._text_mentions_item(text, item)]
        if len(mentioned_items) == 1:
            return mentioned_items[0]
        return None

    def _conversation_subject_key(self, subject: str) -> str:
        cleaned = re.sub(r"(?i)^\s*(re|fw|fwd)\s*:\s*", "", subject or "").strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _text_mentions_item(self, text: str, item: CatalogItem) -> bool:
        item_name = clean_optional_text(getattr(item, "ingredient_name", None))
        if not item_name:
            return False
        text_canonical = self._canonical_match_text(text)
        item_canonical = self._canonical_match_text(item_name)
        if not text_canonical or not item_canonical:
            return False
        if item_canonical in text_canonical:
            return True
        item_tokens = [token for token in item_canonical.split() if len(token) >= 3]
        return bool(item_tokens) and all(token in text_canonical for token in item_tokens)

    def _catalog_item_changed(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        item,
        tenant_id: Any,
    ) -> bool:
        ingredient_name = item.ingredient_name
        previous_candidates = (
            self.db.query(CatalogItem)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .filter(
                CatalogItem.tenant_id == tenant_id,
                CatalogItem.supplier_id == supplier.id,
                CatalogItem.ingredient_name == ingredient_name,
                CatalogItem.catalog_email_id != catalog_email.id,
            )
            .order_by(CatalogEmail.received_at.desc())
            .all()
        )
        previous = next(
            (
                candidate
                for candidate in previous_candidates
                if self._same_item_identity(candidate, item)
            ),
            None,
        )
        if previous is None:
            return True

        return any(
            [
                _nullable_float(previous.price_per_unit) != _nullable_float(item.price_per_unit),
                (previous.currency or "").upper() != (item.currency or "").upper(),
                (previous.lead_time_days or None) != (item.lead_time_days or None),
                (previous.raw_payload or {}).get("lead_time_text") != (item.lead_time_text or None),
                self._item_specification(previous) != self._item_specification(item),
            ]
        )

    def _single_existing_supplier_item(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        item,
        tenant_id: Any,
    ) -> CatalogItem | None:
        ingredient_name = item.ingredient_name
        previous_items = [
            candidate
            for candidate in (
            self.db.query(CatalogItem)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .filter(
                CatalogItem.tenant_id == tenant_id,
                CatalogItem.supplier_id == supplier.id,
                CatalogItem.ingredient_name == ingredient_name,
                CatalogItem.catalog_email_id != catalog_email.id,
            )
            .order_by(CatalogEmail.received_at.desc())
            .all()
            )
            if self._same_item_identity(candidate, item)
        ]
        return previous_items[0] if len(previous_items) == 1 else None

    def _same_item_identity(self, existing: CatalogItem, item) -> bool:
        return self._item_identity_key(existing) == self._item_identity_key(item)

    def _item_identity_key(self, item) -> tuple:
        return (
            str(getattr(item, "ingredient_name", "") or "").strip().lower(),
            self._item_specification(item),
        )

    def _item_specification(self, item) -> str:
        raw_payload = getattr(item, "raw_payload", None) or {}
        value = (
            getattr(item, "specification", None)
            or raw_payload.get("specification")
            or self._notes_payload(getattr(item, "notes", None)).get("specification")
        )
        return (clean_optional_text(value) or "").strip().lower()

    def _touch_supplier_last_email(self, supplier: Supplier, received_at: datetime) -> None:
        if supplier.last_email_date is None or received_at > supplier.last_email_date:
            supplier.last_email_date = received_at

    def _update_supplier_country(self, supplier: Supplier, *texts: str | None) -> None:
        detected_country = detect_supplier_country(*texts)
        current_country = clean_optional_text(getattr(supplier, "country", None)) or UNKNOWN_COUNTRY
        if current_country == UNKNOWN_COUNTRY or detected_country != UNKNOWN_COUNTRY:
            supplier.country = detected_country if detected_country != UNKNOWN_COUNTRY else current_country
        if not clean_optional_text(getattr(supplier, "country", None)):
            supplier.country = UNKNOWN_COUNTRY

    def _classify_document(self, filename: str, ext: str, text: str | None, context_text: str | None = None):
        ext_lower = ext.lower()
        if ext_lower not in CLASSIFIABLE_DOCUMENT_EXTENSIONS:
            return DocumentClassification(CATALOGUE, 0.95, None)
        return classify_document(filename, ext, text, context_text)

    def _is_certificate_pdf(self, filename: str, ext: str, text: str | None = None) -> bool:
        if ext.lower() not in CLASSIFIABLE_DOCUMENT_EXTENSIONS:
            return False
        return self._classify_document(filename, ext, text).category == CERTIFICATE

    def _certificate_type(self, filename: str, text: str | None = None) -> str:
        haystack = f"{filename}\n{text or ''}".lower()
        if "certificate of analysis" in haystack or re.search(r"\bcoa\b", haystack):
            return "COA"
        if "halal" in haystack:
            return "Halal"
        if "kosher" in haystack:
            return "Kosher"
        if "organic" in haystack:
            return "Organic"
        if "fda" in haystack:
            return "FDA"
        if "gmp" in haystack or "cgmp" in haystack:
            return "GMP"
        if "iso" in haystack:
            return "ISO"
        if "lab report" in haystack or "laboratory report" in haystack or "test report" in haystack:
            return "Lab Report"
        return "Certificate"

    def _attach_certificate_refs(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        certificate_refs: list[dict[str, str]],
    ) -> None:
        unique_refs = self._dedupe_certificate_refs(certificate_refs)
        if not unique_refs:
            return

        same_email_items = (
            self.db.query(CatalogItem)
            .filter(
                CatalogItem.catalog_email_id == catalog_email.id,
                CatalogItem.supplier_id == supplier.id,
                CatalogItem.tenant_id == catalog_email.tenant_id,
            )
            .all()
        )
        supplier_items = (
            self.db.query(CatalogItem)
            .filter(
                CatalogItem.supplier_id == supplier.id,
                CatalogItem.tenant_id == catalog_email.tenant_id,
            )
            .all()
        )
        items = []
        seen_items: set[str] = set()
        for item in [*same_email_items, *supplier_items]:
            key = str(getattr(item, "id", None) or id(item))
            if key in seen_items:
                continue
            seen_items.add(key)
            items.append(item)
        pairable_refs: list[dict[str, str]] = []
        for ref in unique_refs:
            material_name = self._certificate_material_name(ref)
            if not material_name:
                logger.info(
                    "Skipping certificate PDF %s: no item name found for pairing",
                    ref.get("name", "Certificate PDF"),
                )
                continue
            pairable = dict(ref)
            pairable["material_hint"] = material_name
            pairable_refs.append(pairable)

        unmatched_refs = list(pairable_refs)
        if items:
            for item in items:
                matches = [ref for ref in pairable_refs if self._certificate_matches_item(ref, item)]
                if matches:
                    self._merge_item_certificate_refs(item, matches)
                    for m in matches:
                        if m in unmatched_refs:
                            unmatched_refs.remove(m)

        if not unmatched_refs:
            return

        for ref in unmatched_refs:
            logger.info(
                "Skipping certificate PDF %s: item name %r did not match any catalogue row",
                ref.get("name", "Certificate PDF"),
                ref.get("material_hint"),
            )

    def _create_catalog_item_from_certificate(
        self,
        catalog_email: CatalogEmail,
        supplier: Supplier,
        ref: dict[str, str],
    ) -> CatalogItem:
        from backend.app.services.document_classifier import _material_hint
        from backend.app.services.country_detection import detect_supplier_country, UNKNOWN_COUNTRY

        ingredient_name = clean_optional_text(ref.get("material_hint"))
        if not ingredient_name or len(ingredient_name) < 2:
            ingredient_name = _material_hint(ref.get("name", ""), ref.get("match_text", ""))

        if not ingredient_name or len(ingredient_name) < 2:
            raw_filename = ref.get("name", "Certificate")
            stem = re.sub(r"\.[A-Za-z0-9]+$", "", raw_filename)
            stem = re.sub(r"(?i)\b(?:certificate of analysis|certificate|cert|coa|analysis|report|pdf|scan|copy)\b", " ", stem)
            stem = re.sub(r"[_-]+", " ", stem).strip()
            ingredient_name = stem[:120] if len(stem) >= 3 else "Certificate Item"

        match_text = ref.get("match_text", "")
        detected_country = detect_supplier_country(match_text, getattr(supplier, "country", None))
        if detected_country == UNKNOWN_COUNTRY:
            detected_country = clean_optional_text(getattr(supplier, "country", None)) or UNKNOWN_COUNTRY

        if detected_country != UNKNOWN_COUNTRY and getattr(supplier, "country", None) in {None, "", UNKNOWN_COUNTRY}:
            supplier.country = detected_country

        cert_pdf_obj = {
            "name": clean_optional_text(ref.get("name")) or "Certificate PDF",
            "url": ref.get("url", ""),
            "type": clean_optional_text(ref.get("type")) or "Certificate",
        }
        if clean_optional_text(ref.get("storage_path")):
            cert_pdf_obj["storage_path"] = ref["storage_path"]

        raw_payload = {
            "source": "certificate_document",
            "source_document": ref.get("name", "Certificate"),
            "specification": ref.get("type", "Certificate"),
            "country_of_origin": detected_country,
            "country": detected_country,
            "certificate_pdfs": [cert_pdf_obj],
        }

        new_item = CatalogItem(
            id=uuid4(),
            tenant_id=catalog_email.tenant_id,
            catalog_email_id=catalog_email.id,
            supplier_id=supplier.id,
            ingredient_name=ingredient_name,
            price_per_unit=None,
            currency="",
            available_qty=None,
            unit="kg",
            valid_until=None,
            lead_time_days=None,
            moq=None,
            raw_payload=raw_payload,
        )
        self.db.add(new_item)
        logger.info(
            "Created new catalog item '%s' from certificate '%s' supplier=%s country=%s",
            ingredient_name,
            ref.get("name"),
            getattr(supplier, "email_domain", "unknown"),
            detected_country,
        )
        return new_item

    def _certificate_matches_item(self, certificate_ref: dict[str, str], item: CatalogItem) -> bool:
        material_name = self._certificate_material_name(certificate_ref)
        if not material_name:
            return False
        cert_text = self._canonical_match_text(material_name)
        item_text = self._canonical_match_text(
            f"{item.ingredient_name} {(item.raw_payload or {}).get('specification', '')}"
        )
        item_tokens = [
            token
            for token in item_text.split()
            if len(token) >= 3 and token not in {"extract", "powder", "liquid", "grade", "hplc", "oil", "usp", "food"}
        ]
        if not item_tokens:
            return False
        matched = sum(1 for token in item_tokens if token in cert_text)
        if matched >= min(2, len(item_tokens)):
            return True
        if any(len(token) >= 6 and token in cert_text for token in item_tokens):
            return True
        material_hint = self._canonical_match_text(material_name)
        return bool(material_hint and (material_hint in item_text or item_text in material_hint))

    def _certificate_material_name(self, certificate_ref: dict[str, str]) -> str | None:
        material_hint = clean_optional_text(certificate_ref.get("material_hint"))
        if material_hint:
            return self._clean_certificate_material_name(material_hint)

        from backend.app.services.document_classifier import _material_hint

        return self._clean_certificate_material_name(
            _material_hint(certificate_ref.get("name", ""), certificate_ref.get("match_text", ""))
        )

    def _clean_certificate_material_name(self, value: str | None) -> str | None:
        cleaned = clean_optional_text(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"\.[A-Za-z0-9]+$", "", cleaned)
        cleaned = re.sub(r"[_-]+", " ", cleaned)
        cleaned = re.sub(
            r"(?i)\b(?:certificate of analysis|certificate|cert|coa|analysis|report|pdf|scan|copy|doc|document)\b",
            " ",
            cleaned,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_:.,")
        if len(cleaned) < 3:
            return None
        return cleaned[:120]

    def _merge_item_certificate_refs(self, item: CatalogItem, refs: list[dict[str, str]]) -> None:
        raw_payload = dict(item.raw_payload or {})
        existing = raw_payload.get("certificate_pdfs")
        if not isinstance(existing, list):
            existing = []

        merged = self._dedupe_certificate_refs(
            [
                *(ref for ref in existing if isinstance(ref, dict)),
                *refs,
            ]
        )
        raw_payload["certificate_pdfs"] = merged
        item.raw_payload = raw_payload
        self.db.add(item)

    def _dedupe_certificate_refs(self, refs: list[dict[str, str]]) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        for ref in refs:
            url = clean_optional_text(ref.get("url"))
            name = clean_optional_text(ref.get("name")) or "Certificate PDF"
            if not url:
                continue
            key = clean_optional_text(ref.get("storage_path")) or url
            if key in seen:
                continue
            seen.add(key)
            deduped.append(
                {
                    "name": name,
                    "url": url,
                    "type": clean_optional_text(ref.get("type")) or "Certificate",
                    **({"storage_path": ref["storage_path"]} if clean_optional_text(ref.get("storage_path")) else {}),
                    **({"match_text": ref["match_text"]} if clean_optional_text(ref.get("match_text")) else {}),
                    **({"material_hint": ref["material_hint"]} if clean_optional_text(ref.get("material_hint")) else {}),
                }
            )
        return deduped

    def _canonical_match_text(self, value: str | None) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())

    def _pack_size_for_item(self, text: str, ingredient_name: str) -> str | None:
        ingredient = ingredient_name.lower()
        for line in text.splitlines():
            if ingredient in line.lower():
                return extract_pack_size(line)
        return None

    def _notes_payload(self, notes: str | None) -> dict[str, str]:
        payload: dict[str, str] = {}
        if not notes:
            return payload
        for part in notes.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key and value:
                cleaned_value = clean_optional_text(value.strip().strip("'\""))
                if cleaned_value:
                    payload[key.strip()] = cleaned_value
        return payload

    def _corrections_from_notes(self, notes: str | None) -> list[dict[str, str]]:
        raw_value = self._notes_payload(notes).get("auto_corrections")
        if not raw_value:
            return []
        corrections: list[dict[str, str]] = []
        for item in raw_value.split("|"):
            field, separator, rest = item.partition(":")
            original, arrow, corrected = rest.partition("->")
            field = field.strip()
            original = original.strip()
            corrected = corrected.strip()
            if separator and arrow and field and original and corrected:
                corrections.append({"field": field, "from": original, "to": corrected, "rule": "normalizer_auto_correction"})
        return corrections

    def _compact_payload(self, payload: dict) -> dict:
        cleaned: dict = {}
        for key, value in payload.items():
            if isinstance(value, str):
                cleaned_value = clean_optional_text(value)
                if cleaned_value is not None:
                    cleaned[key] = cleaned_value
            elif value is not None:
                cleaned[key] = value
        return cleaned

    def _exact_display_payload(self, item, text: str) -> dict[str, str]:
        payload: dict[str, str] = {}
        notes_payload = self._notes_payload(item.notes)

        if item.lead_time_text:
            payload["lead_time_text"] = str(item.lead_time_text)
        elif notes_payload.get("lead_time"):
            payload["lead_time_text"] = notes_payload["lead_time"]

        source_price = self._source_number_text(text, item.ingredient_name, item.price_per_unit)
        payload["price_display"] = self._richer_display_value(notes_payload.get("original_price"), source_price)

        source_quantity = self._source_number_text(text, item.ingredient_name, item.available_qty)
        if notes_payload.get("original_quantity"):
            original_quantity = notes_payload["original_quantity"]
            if item.unit and not re.search(r"[A-Za-z]", original_quantity):
                note_quantity = f"{original_quantity} {item.unit}"
            else:
                note_quantity = original_quantity
            payload["quantity_display"] = self._richer_display_value(note_quantity, source_quantity)
        else:
            payload["quantity_display"] = source_quantity

        if item.moq is not None:
            payload["moq_display"] = notes_payload.get("moq") or str(item.moq)
        return {key: value for key, value in payload.items() if value}

    def _richer_display_value(self, preferred: str | None, fallback: str | None) -> str | None:
        preferred = clean_optional_text(preferred)
        fallback = clean_optional_text(fallback)
        if not preferred:
            return fallback
        if not fallback:
            return preferred

        def richness(value: str) -> int:
            score = len(value)
            if re.search(r"(?:USD|INR|EUR|GBP|AED|CNY|JPY|CAD|AUD|SGD|CHF|Rs\.?|₹|\$|€|£)", value, flags=re.IGNORECASE):
                score += 30
            if "/" in value or re.search(r"\b(?:kg|g|mg|lb|bag|drum|mt|ton)\b", value, flags=re.IGNORECASE):
                score += 20
            if "(" in value and ")" in value:
                score += 10
            return score

        return fallback if richness(fallback) > richness(preferred) else preferred

    def _source_number_text(self, text: str, ingredient_name: str, value: Any) -> str | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except Exception:
            return None
        if numeric == 0:
            exact_value = "0"
        elif numeric.is_integer():
            exact_value = str(int(numeric))
        else:
            exact_value = f"{numeric:g}"

        if not exact_value:
            return None

        for line in text.splitlines():
            if ingredient_name.lower() not in line.lower():
                continue
            compact = line.replace(",", "")
            match = re.search(rf"(?<!\d){re.escape(exact_value)}(?:\.0+)?(?!\d)", compact)
            if match:
                value_text = match.group(0)
                display_match = re.search(
                    rf"(?:(?:USD|INR|EUR|GBP|AED|CNY|JPY|CAD|AUD|SGD|CHF|Rs\.?|₹|\$|€|£)\s*)?"
                    rf"{re.escape(value_text)}"
                    rf"(?:\s*(?:/[A-Za-z][A-Za-z0-9-]*|[A-Za-z][A-Za-z0-9-]*))?"
                    rf"(?:\s*\([A-Za-z0-9 .,/+-]+\))?",
                    compact,
                    flags=re.IGNORECASE,
                )
                if display_match:
                    return " ".join(display_match.group(0).split())
                return value_text
        return exact_value

    def _email_has_items(self, raw_email_id: str, tenant_id: Any | None = None) -> bool:
        query = (
            self.db.query(CatalogItem)
            .join(CatalogEmail, CatalogItem.catalog_email_id == CatalogEmail.id)
            .filter(CatalogEmail.raw_email_id.like(f"{raw_email_id}%"))
        )
        if tenant_id:
            query = query.filter(CatalogEmail.tenant_id == tenant_id)
        return query.first() is not None

    def _existing_email_status(self, raw_email_id: str, tenant_id: Any | None = None) -> str | None:
        query = self.db.query(CatalogEmail.processing_status).filter(CatalogEmail.raw_email_id == raw_email_id)
        if tenant_id:
            query = query.filter(CatalogEmail.tenant_id == tenant_id)
        row = query.first()
        return row[0] if row else None

    def _status_key(self, status: str | None) -> str:
        return str(status or "").strip().lower()

    def _should_skip_logged_email(self, status: str | None) -> bool:
        key = self._status_key(status)
        return bool(key)

    def _is_retryable_logged_email(self, status: str | None) -> bool:
        key = self._status_key(status)
        if key.endswith("_permanent"):
            return False
        return key.startswith(("failed", "error", "partial"))

    def _terminal_retry_status(self, status: str | None) -> str:
        key = self._status_key(status)
        return "partial_permanent" if key.startswith("partial") else "failed_permanent"

    def _mark_email_retry_attempt(self, raw_email_id: str, tenant_id: Any) -> None:
        email_row = (
            self.db.query(CatalogEmail)
            .filter(CatalogEmail.raw_email_id == raw_email_id)
            .filter(CatalogEmail.tenant_id == tenant_id)
            .first()
        )
        if not email_row:
            return
        email_row.retry_count = int(email_row.retry_count or 0) + 1
        email_row.last_attempt_at = datetime.now(UTC)
        self.db.commit()

    def _raw_email_base_id(self, raw_email_id: str, account_id: Any) -> str:
        account_prefix = f"{account_id}:"
        if raw_email_id.startswith(account_prefix):
            parts = raw_email_id.split(":")
            return ":".join(parts[:3]) if len(parts) >= 3 else raw_email_id
        return raw_email_id.split(":")[0] if ":" in raw_email_id else raw_email_id

    def _message_received_at(self, message: Message) -> datetime:
        try:
            date_hdr = message.get("Date")
            if date_hdr:
                parsed_dt = email.utils.parsedate_to_datetime(date_hdr)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=UTC)
                return parsed_dt
        except Exception:
            logger.warning("Failed parsing Date header from email, falling back to current time")
        return datetime.now(UTC)

    def _message_fingerprint(
        self,
        message: Message,
        sender: str,
        subject: str,
        received_at: datetime | None = None,
    ) -> str:
        message_id = (message.get("Message-ID") or message.get("Message-Id") or "").strip().strip("<>")
        if message_id:
            return f"message-id:{message_id.lower()}"

        normalized_subject = " ".join((subject or "").lower().split())
        received_marker = received_at.isoformat() if received_at else ""
        return f"fallback:{sender.strip().lower()}|{normalized_subject}|{received_marker}"

    def _csv_terms(self, raw: str | None) -> list[str]:
        return [term.strip().lower() for term in (raw or "").split(",") if term.strip()]

    def _text_matches_any(self, text: str, terms: list[str]) -> bool:
        text_lower = text.lower()
        return any(term in text_lower for term in terms)

    def _sender_matches_any(self, sender: str, display_name: str, terms: list[str]) -> bool:
        sender_lower = sender.lower()
        display_lower = (display_name or "").lower()
        domain = get_supplier_domain(sender)
        return any(
            term in sender_lower or term in display_lower or term == domain
            for term in terms
        )

    def _is_irrelevant_or_marketing_email(
        self,
        *,
        message: Message,
        sender: str,
        subject: str,
        body_text: str,
        labels: str,
        list_unsubscribe: str,
        precedence: str,
    ) -> bool:
        sender_lower = sender.lower()
        subject_lower = subject.lower()
        labels_lower = labels.lower()
        body_sample = body_text[:4000].lower()
        combined = f"{sender_lower} {subject_lower} {body_sample}"
        strong_supplier_terms = [term for term in SUPPLIER_INTENT_TERMS if term not in {"offer", "price", "pricing"}]

        marketing_headers = (
            "promotions" in labels_lower
            or "category-promo" in labels_lower
            or precedence.lower() in {"bulk", "list"}
            or bool(list_unsubscribe)
            or bool(message.get("List-Id"))
        )
        has_supplier_intent = self._text_matches_any(combined, strong_supplier_terms)
        has_irrelevant_terms = self._text_matches_any(combined, list(IRRELEVANT_MAIL_TERMS))

        if marketing_headers and not has_supplier_intent:
            return True
        if has_irrelevant_terms and not has_supplier_intent:
            return True
        if sender_lower.startswith(("no-reply@", "noreply@", "do-not-reply@", "donotreply@")):
            return True
        return False

    def _has_supplier_catalogue_intent(
        self,
        subject: str,
        body_text: str,
        attachments: list[dict],
    ) -> bool:
        attachment_names = " ".join(str(att.get("filename", "")) for att in attachments)
        text = f"{subject} {attachment_names} {body_text[:8000]}".lower()
        if self._text_matches_any(text, list(SUPPLIER_INTENT_TERMS)):
            return True

        # Structured/image attachments from a supplier mailbox are often terse, e.g. "July rates.xlsx".
        parseable_extensions = {
            ".xlsx", ".xls", ".csv", ".pdf", ".docx", ".doc",
            ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
        }
        return any(str(att.get("ext", "")).lower() in parseable_extensions for att in attachments)

    def _mark_seen(self, client: imaplib.IMAP4, msg_uid: bytes) -> None:
        logger.debug("Leaving IMAP message uid=%s unread in the employee mailbox", msg_uid)

    def _restore_unseen_after_processing(self, client: imaplib.IMAP4, msg_uid: bytes) -> None:
        try:
            client.uid("store", msg_uid, "-FLAGS.SILENT", "\\Seen")
            logger.debug("Restored IMAP message uid=%s to unread after MediCORE processing", msg_uid)
        except Exception:
            logger.warning("Unable to restore IMAP message uid=%s to unread", msg_uid, exc_info=True)

    def _upsert_supplier(self, sender: str, display_name: str | None = None, tenant_id: Any | None = None) -> Supplier:
        if tenant_id is None:
            # Looking up by domain without a tenant can attach one employee's
            # import to another employee's supplier record.
            raise ValueError("A tenant_id is required when creating or finding a supplier.")
        domain = get_supplier_domain(sender)
        supplier = self.db.query(Supplier).filter(
            Supplier.email_domain == domain,
            Supplier.tenant_id == tenant_id,
        ).first()

        cleaned_display_name = display_name.strip() if display_name else None

        if supplier:
            if not clean_optional_text(getattr(supplier, "country", None)):
                supplier.country = UNKNOWN_COUNTRY
                self.db.add(supplier)
            if cleaned_display_name and supplier.name != cleaned_display_name:
                supplier.name = cleaned_display_name
                self.db.add(supplier)
            return supplier

        supplier_name = cleaned_display_name or sender

        supplier = Supplier(
            id=uuid4(),
            tenant_id=tenant_id,
            name=supplier_name,
            email_domain=domain,
            country=UNKNOWN_COUNTRY,
        )
        self.db.add(supplier)
        self.db.flush()
        return supplier

    def _collect_attachments(self, message: Message) -> list[dict]:
        attachments = []
        total_attachment_bytes = 0
        total_data_uri_bytes = 0
        data_uri_count = 0

        for part in message.walk():
            if len(attachments) >= MAX_ATTACHMENT_COUNT:
                logger.warning("Reached maximum attachment limit (%s) for message; ignoring remaining parts", MAX_ATTACHMENT_COUNT)
                break

            filename = part.get_filename()
            if not filename:
                content_type = part.get_content_type()
                if content_type and content_type.lower().startswith("image/"):
                    name_param = part.get_param("name")
                    content_id = part.get("Content-ID")
                    sub_ext = content_type.split("/")[-1].lower()
                    if sub_ext == "jpeg":
                        sub_ext = "jpg"
                    if name_param:
                        filename = name_param
                    elif content_id:
                        clean_id = re.sub(r"[<>]", "", content_id).strip()
                        filename = f"inline_{clean_id}.{sub_ext}"
                    else:
                        filename = f"inline_image_{len(attachments) + 1}.{sub_ext}"
                else:
                    filename = None

            # Check for inline base64 images in HTML parts first (if applicable)
            if part.get_content_type() == "text/html":
                try:
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    html_str = payload.decode(charset, errors="ignore")
                    import base64
                    data_uri_matches = re.findall(
                        r'src=["\']data:image/(png|jpeg|jpg|webp|bmp|tiff);base64,([^"\'\s]+)["\']',
                        html_str,
                        flags=re.IGNORECASE,
                    )
                    for img_format, base64_data in data_uri_matches:
                        if len(attachments) >= MAX_ATTACHMENT_COUNT:
                            break
                        if data_uri_count >= MAX_DATA_URI_COUNT:
                            logger.warning("Skipping inline data URI image: reached max data URI count (%s)", MAX_DATA_URI_COUNT)
                            break
                        # Pre-check base64 length before decoding to prevent memory exhaustion
                        if len(base64_data) > int(MAX_DATA_URI_BYTES * 1.37) + 100:
                            logger.warning("Skipping inline data URI image exceeding %s bytes", MAX_DATA_URI_BYTES)
                            continue
                        try:
                            img_bytes = base64.b64decode(base64_data)
                        except Exception as b64_err:
                            logger.warning("Failed decoding inline base64 image: %s", b64_err)
                            continue

                        if len(img_bytes) > MAX_DATA_URI_BYTES:
                            logger.warning("Skipping decoded inline image exceeding %s bytes", MAX_DATA_URI_BYTES)
                            continue
                        if total_data_uri_bytes + len(img_bytes) > MAX_TOTAL_DATA_URI_BYTES:
                            logger.warning("Skipping decoded inline image: exceeds aggregate data URI budget (%s bytes)", MAX_TOTAL_DATA_URI_BYTES)
                            break
                        if total_attachment_bytes + len(img_bytes) > MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES:
                            logger.warning("Skipping inline image: exceeds total email attachment budget")
                            break

                        ext = f".{img_format.lower()}"
                        if ext == ".jpeg":
                            ext = ".jpg"
                        img_name = f"embedded_html_image_{len(attachments) + 1}{ext}"

                        is_valid, canonical_mime, err_msg = validate_document_bytes(
                            img_bytes,
                            img_name,
                            declared_mime=f"image/{img_format.lower()}",
                            max_bytes=MAX_DATA_URI_BYTES,
                        )
                        if not is_valid:
                            logger.warning("Skipping invalid inline base64 image %s: %s", img_name, err_msg)
                            continue

                        attachments.append({
                            "filename": img_name,
                            "payload": img_bytes,
                            "ext": ext,
                            "mime_type": canonical_mime,
                        })
                        total_data_uri_bytes += len(img_bytes)
                        total_attachment_bytes += len(img_bytes)
                        data_uri_count += 1
                except Exception as html_err:
                    logger.warning("Error scanning HTML for base64 inline images: %s", html_err)

            if not filename:
                continue

            # Decode file name if encoded
            try:
                decoded = decode_header(filename)
                filename = "".join(
                    [
                        t[0].decode(t[1] or "utf-8", errors="ignore") if isinstance(t[0], bytes) else t[0]
                        for t in decoded
                    ]
                )
            except Exception:
                pass

            safe_filename = sanitize_filename(filename)
            file_ext = Path(safe_filename.lower()).suffix
            if not file_ext:
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            if len(payload) > MAX_DOCUMENT_BYTES:
                logger.warning("Skipping attachment %s because it exceeds the 30 MB processing limit", safe_filename)
                continue

            if total_attachment_bytes + len(payload) > MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES:
                logger.warning("Skipping attachment %s: exceeds aggregate attachment limit (%s bytes)", safe_filename, MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES)
                continue

            declared_mime = part.get_content_type()
            is_valid, canonical_mime, err_msg = validate_document_bytes(
                payload,
                safe_filename,
                declared_mime=declared_mime,
                max_bytes=MAX_DOCUMENT_BYTES,
            )
            if not is_valid:
                logger.warning("Skipping invalid attachment %s: %s", safe_filename, err_msg)
                continue

            attachments.append({
                "filename": safe_filename,
                "payload": payload,
                "ext": file_ext,
                "mime_type": canonical_mime,
            })
            total_attachment_bytes += len(payload)

        return attachments

    def _get_email_body_text(self, message: Message) -> str:
        plain_parts: list[str] = []
        html_parts: list[str] = []
        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if "attachment" in content_disposition:
                    continue
                if content_type in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        decoded = payload.decode(charset, errors="ignore")
                        if content_type == "text/plain":
                            plain_parts.append(decoded)
                        else:
                            html_parts.append(self._html_to_text(decoded))
        else:
            payload = message.get_payload(decode=True)
            if payload:
                charset = message.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="ignore")
                if message.get_content_type() == "text/html":
                    html_parts.append(self._html_to_text(decoded))
                else:
                    plain_parts.append(decoded)
        preferred_parts = plain_parts if any(part.strip() for part in plain_parts) else html_parts
        return self._clean_email_body("\n\n".join(part for part in preferred_parts if part.strip()))

    def _body_preview(self, body_text: str | None) -> str | None:
        cleaned = self._clean_email_body(body_text)
        return sanitize_preview_text(cleaned, max_chars=500)

    def _html_to_text(self, html: str) -> str:
        parser = _HTMLTextExtractor()
        try:
            parser.feed(html)
            return parser.text()
        except Exception:
            return ""

    def _clean_email_body(self, body_text: str | None) -> str:
        text = str(body_text or "")
        if not text.strip():
            return ""
        text = re.sub(r"(?is)<(script|style|head|meta|title|noscript)\b.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"\bwww\.\S+", " ", text)
        text = re.sub(r"\S+@\S+\.\S+", " ", text)
        text = re.sub(r"(?im)^\s*(from|sent|to|cc|bcc|subject)\s*:.*$", " ", text)
        text = re.split(
            r"(?im)^\s*(?:On .+ wrote:|From:.+|-----Original Message-----|_{5,}|-{5,}|Forwarded message)\s*$",
            text,
            maxsplit=1,
        )[0]
        text = re.split(
            r"(?im)^\s*(?:(?:thanks|thank you|regards)\s*[,.!]*|(?:best regards|kind regards|warm regards|sent from my)\b.*)$",
            text,
            maxsplit=1,
        )[0]
        lines: list[str] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip(" \t|-_")
            if not line:
                continue
            if re.search(r"(?i)\b(unsubscribe|view in browser|privacy policy|manage preferences|read more)\b", line):
                continue
            if len(line) > 240 and not re.search(r"(?i)\b(price|quote|quotation|catalog|catalogue|ingredient|product|quantity|moq|lead time)\b", line):
                line = line[:240].rstrip() + "..."
            key = re.sub(r"\W+", "", line.lower())
            if key and key in seen:
                continue
            seen.add(key)
            lines.append(line)
        return "\n".join(lines).strip()

    def _extract_docx_text(self, file_path: Path) -> str:
        text = self._extract_with_anydoc(file_path, fallback_format=file_path.suffix.lower().lstrip("."))
        text_parts = [text] if text else []

        if not self._native_document_text_sufficient(text):
            image_text = self._extract_office_embedded_image_text(
                file_path,
                fallback_format=file_path.suffix.lower().lstrip("."),
            )
            if image_text:
                text_parts.append(image_text)

        return "\n\n".join(dict.fromkeys(part.strip() for part in text_parts if part.strip()))

    def _native_document_text_sufficient(self, text: str | None) -> bool:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return False
        word_count = len(re.findall(r"[A-Za-z0-9]{2,}", cleaned))
        table_signals = cleaned.count("|") + len(re.findall(r"\b(?:price|qty|quantity|specification|MOQ|USD|INR|kg|certificate|COA)\b", cleaned, re.IGNORECASE))
        return word_count >= 60 and table_signals >= 2

    def _extract_word_text(self, file_path: Path, ext: str) -> str:
        text = self._extract_with_anydoc(file_path, fallback_format=ext.lstrip("."))
        text_parts = [text] if text else []

        if not self._native_document_text_sufficient(text):
            image_text = self._extract_office_embedded_image_text(file_path, fallback_format=ext.lstrip("."))
            if image_text:
                text_parts.append(image_text)

        return "\n\n".join(dict.fromkeys(part.strip() for part in text_parts if part.strip()))

    def _extract_office_embedded_image_text(self, file_path: Path, fallback_format: str | None = None) -> str:
        texts = self._extract_anydoc_embedded_image_text(file_path, fallback_format=fallback_format)
        if texts:
            return texts
        if file_path.suffix.lower() == ".docx":
            return self._extract_docx_zip_embedded_image_text(file_path)
        return ""

    def _extract_anydoc_embedded_image_text(self, file_path: Path, fallback_format: str | None = None) -> str:
        try:
            from backend.app.pipeline.pipeline import process_document

            result = process_document(file_path)
            return result.full_text()
        except Exception:
            logger.debug("Pipeline embedded extraction failed for %s", file_path.name, exc_info=True)
            return ""

    def _extract_docx_zip_embedded_image_text(self, file_path: Path) -> str:
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
        texts: list[str] = []
        try:
            from backend.app.pipeline.ingestion.safe_zip import inspect_and_validate_zip
            inspect_and_validate_zip(file_path)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
                tmp_path = Path(tmp_dir)
                with zipfile.ZipFile(file_path) as docx:
                    media_names = [
                        name
                        for name in docx.namelist()
                        if name.startswith("word/media/") and Path(name).suffix.lower() in image_exts
                    ][:10]
                    for index, media_name in enumerate(media_names, start=1):
                        image_path = tmp_path / f"docx-image-{index}{Path(media_name).suffix.lower()}"
                        image_path.write_bytes(docx.read(media_name))
                        image_text = self._extract_image_text(image_path)
                        if image_text.strip():
                            texts.append(f"[DOCX EMBEDDED IMAGE OCR] {Path(media_name).name}\n{image_text.strip()}")
                if texts:
                    logger.info("OCR extracted embedded image text from %s image(s) in %s", len(texts), file_path.name)
        except Exception:
            logger.debug("DOCX embedded image OCR failed for %s", file_path.name, exc_info=True)
        return "\n\n".join(dict.fromkeys(texts))

    def _extract_spreadsheet_text(self, file_path: Path, ext: str) -> str:
        if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
            xlsx_text = self._extract_xlsx_tables_text(file_path)
            if xlsx_text:
                return xlsx_text
        if ext in (".xls", ".xlsx", ".xlsm", ".xltx", ".xltm"):
            workbook_text = self._extract_excel_tables_with_pandas(file_path, ext)
            if workbook_text:
                return workbook_text
        return self._extract_with_anydoc(file_path, fallback_format=ext.lstrip("."))

    def _extract_csv_tables_text(self, file_path: Path) -> str:
        return self._extract_with_anydoc(file_path, fallback_format="csv")

    def _extract_xlsx_tables_text(self, file_path: Path) -> str:
        text = self._extract_xlsx_tables_from_xml(file_path)
        if text:
            return text
        pandas_text = self._extract_excel_tables_with_pandas(file_path, file_path.suffix.lower())
        if pandas_text:
            return pandas_text
        return self._extract_with_anydoc(file_path, fallback_format=file_path.suffix.lower().lstrip("."))

    def _extract_excel_tables_with_pandas(self, file_path: Path, ext: str) -> str:
        try:
            import pandas as pd

            engine = "xlrd" if ext == ".xls" else "openpyxl"
            sections: list[str] = []
            global_table_number = 0
            with pd.ExcelFile(file_path, engine=engine) as excel_file:
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None, dtype=str).fillna("")
                    cells: dict[tuple[int, int], str] = {}
                    for row_offset, row in enumerate(df.itertuples(index=False), start=1):
                        for col_offset, value in enumerate(row, start=1):
                            cleaned = " ".join(str(value or "").split()).strip()
                            if cleaned:
                                cells[(row_offset, col_offset)] = cleaned
                    for table in self._detect_xlsx_tables(cells):
                        global_table_number += 1
                        sections.append(
                            self._format_xlsx_table(
                                sheet_name,
                                global_table_number,
                                table["start_row"],
                                table["start_col"],
                                table["header"],
                                table["rows"],
                            )
                        )
            text = "\n\n".join(sections).strip()
            if text:
                logger.info(
                    "Pandas workbook scanner extracted %s table(s) from %s",
                    global_table_number,
                    file_path.name,
                )
            return text
        except Exception:
            logger.debug("Pandas workbook scanner failed for %s", file_path.name, exc_info=True)
            return ""

    def _extract_xlsx_tables_from_xml(self, file_path: Path) -> str:
        try:
            from backend.app.pipeline.ingestion.safe_zip import inspect_and_validate_zip
            inspect_and_validate_zip(file_path)
            with zipfile.ZipFile(file_path) as workbook:
                shared_strings = self._xlsx_shared_strings(workbook)
                sheets = self._xlsx_sheets(workbook)[:10]
                sections: list[str] = []
                global_table_number = 0
                for sheet_name, sheet_path in sheets:
                    try:
                        cells = self._xlsx_sheet_cells(workbook, sheet_path, shared_strings)
                    except Exception:
                        logger.debug("Failed reading worksheet %s in %s", sheet_name, file_path.name, exc_info=True)
                        continue
                    for table in self._detect_xlsx_tables(cells):
                        global_table_number += 1
                        sections.append(
                            self._format_xlsx_table(
                                sheet_name,
                                global_table_number,
                                table["start_row"],
                                table["start_col"],
                                table["header"],
                                table["rows"],
                            )
                        )
                text = "\n\n".join(sections).strip()
                if text:
                    logger.info(
                        "XLSX XML scanner extracted %s table(s) from %s",
                        global_table_number,
                        file_path.name,
                    )
                return text
        except Exception:
            logger.debug("XLSX XML scanner failed for %s; falling back to anydoc", file_path.name, exc_info=True)
            return ""

    def _xlsx_shared_strings(self, workbook: zipfile.ZipFile) -> list[str]:
        try:
            root = self._xml_root(workbook.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        strings: list[str] = []
        for si in root.findall("s:si", ns):
            text = "".join(node.text or "" for node in si.findall(".//s:t", ns))
            strings.append(" ".join(text.split()).strip())
        return strings

    def _xlsx_sheets(self, workbook: zipfile.ZipFile) -> list[tuple[str, str]]:
        root = self._xml_root(workbook.read("xl/workbook.xml"))
        rels_root = self._xml_root(workbook.read("xl/_rels/workbook.xml.rels"))
        workbook_ns = {
            "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        targets = {
            rel.attrib.get("Id"): rel.attrib.get("Target", "")
            for rel in rels_root.findall("r:Relationship", rel_ns)
        }
        sheets: list[tuple[str, str]] = []
        for sheet in root.findall(".//s:sheet", workbook_ns):
            rel_id = sheet.attrib.get(f"{{{workbook_ns['r']}}}id")
            target = targets.get(rel_id)
            if not target:
                continue
            path = target.lstrip("/")
            if not path.startswith("xl/"):
                path = f"xl/{path}"
            sheets.append((sheet.attrib.get("name", "Sheet"), path))
        return sheets

    def _xlsx_sheet_cells(
        self,
        workbook: zipfile.ZipFile,
        sheet_path: str,
        shared_strings: list[str],
    ) -> dict[tuple[int, int], str]:
        root = self._xml_root(workbook.read(sheet_path))
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        cells: dict[tuple[int, int], str] = {}
        for cell in root.findall(".//s:sheetData/s:row/s:c", ns):
            ref = cell.attrib.get("r", "")
            row_index, col_index = self._xlsx_cell_ref_to_indexes(ref)
            if row_index <= 0 or col_index <= 0:
                continue
            text = self._xlsx_cell_text(cell, shared_strings, ns)
            if text:
                cells[(row_index, col_index)] = text
        for start_row, start_col, end_row, end_col in self._xlsx_merged_ranges(root, ns):
            anchor = cells.get((start_row, start_col), "")
            if not anchor or not self._should_propagate_merged_header(anchor):
                continue
            for row_index in range(start_row, end_row + 1):
                for col_index in range(start_col, end_col + 1):
                    cells.setdefault((row_index, col_index), anchor)
        return cells

    def _xlsx_merged_ranges(self, root: Any, ns: dict[str, str]) -> list[tuple[int, int, int, int]]:
        ranges: list[tuple[int, int, int, int]] = []
        for merge_cell in root.findall(".//s:mergeCells/s:mergeCell", ns):
            ref = merge_cell.attrib.get("ref", "")
            if ":" not in ref:
                continue
            start_ref, end_ref = ref.split(":", 1)
            start_row, start_col = self._xlsx_cell_ref_to_indexes(start_ref)
            end_row, end_col = self._xlsx_cell_ref_to_indexes(end_ref)
            if start_row and start_col and end_row and end_col:
                ranges.append((start_row, start_col, end_row, end_col))
        return ranges

    def _should_propagate_merged_header(self, value: str) -> bool:
        field = _header_cell_metadata(value).get("field")
        return field in {"price", "qty", "unit", "currency", "moq", "lead_time", "pack", "specification"}

    def _xlsx_cell_text(self, cell: Any, shared_strings: list[str], ns: dict[str, str]) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "s":
            value = cell.find("s:v", ns)
            try:
                return shared_strings[int(value.text or "0")].strip() if value is not None else ""
            except (IndexError, ValueError):
                return ""
        if cell_type == "inlineStr":
            return " ".join((node.text or "") for node in cell.findall(".//s:t", ns)).strip()
        value = cell.find("s:v", ns)
        if value is None or value.text is None:
            return ""
        return " ".join(value.text.split()).strip()

    def _detect_xlsx_tables(self, cells: dict[tuple[int, int], str]) -> list[dict[str, Any]]:
        if not cells:
            return []
        row_columns: dict[int, list[int]] = defaultdict(list)
        for (row, col), value in cells.items():
            if value:
                row_columns[row].append(col)
        rows = sorted(row_columns)
        tables: list[dict[str, Any]] = []
        occupied_headers: set[tuple[int, int, int]] = set()
        occupied_ranges: list[tuple[int, int, int, int]] = []
        for row_index in rows:
            populated_cols = sorted(row_columns[row_index])
            for band in self._contiguous_number_bands(populated_cols, max_gap=1):
                start_col, end_col = band[0], band[-1]
                if any(
                    row_index <= range_end_row and start_col <= range_end_col and end_col >= range_start_col
                    for range_start_col, range_end_col, range_end_row, _ in occupied_ranges
                ):
                    continue
                header = self._xlsx_header_candidate(cells, row_index, start_col, end_col)
                if not header:
                    continue
                header_key = (row_index, start_col, end_col)
                if header_key in occupied_headers:
                    continue
                data_rows, end_row = self._xlsx_table_rows(cells, row_index, start_col, end_col)
                if not data_rows:
                    continue
                tables.append(
                    {
                        "start_row": row_index,
                        "start_col": start_col,
                        "end_row": end_row,
                        "header": header,
                        "rows": data_rows,
                    }
                )
                occupied_headers.add((row_index, start_col, end_col))
                occupied_ranges.append((start_col, end_col, end_row, row_index))
        tables.sort(key=lambda table: (table["start_row"], table["start_col"]))
        return tables

    def _xlsx_header_candidate(
        self,
        cells: dict[tuple[int, int], str],
        row_index: int,
        start_col: int,
        end_col: int,
    ) -> list[str] | None:
        current = [cells.get((row_index, col), "") for col in range(start_col, end_col + 1)]
        previous = [cells.get((row_index - 1, col), "") for col in range(start_col, end_col + 1)]
        if any(clean_optional_text(value) for value in previous):
            combined = self._combine_header_rows(previous, current)
            if self._is_catalogue_table_header(combined) and (
                not self._is_catalogue_table_header(current)
                or self._header_field_count(combined) > self._header_field_count(current)
            ):
                return combined
        if self._is_catalogue_table_header(current):
            return current
        next_row = [cells.get((row_index + 1, col), "") for col in range(start_col, end_col + 1)]
        if any(clean_optional_text(value) for value in next_row):
            combined = self._combine_header_rows(current, next_row)
            if self._is_catalogue_table_header(combined):
                return combined
        return None

    def _header_field_count(self, values: list[str]) -> int:
        return len(_header_map([value for value in values if clean_optional_text(value)]))

    def _combine_header_rows(self, upper: list[str], lower: list[str]) -> list[str]:
        width = max(len(upper), len(lower))
        combined: list[str] = []
        for index in range(width):
            top = clean_optional_text(upper[index] if index < len(upper) else "")
            bottom = clean_optional_text(lower[index] if index < len(lower) else "")
            if top and bottom and top.lower() not in bottom.lower():
                combined.append(f"{top} {bottom}")
            else:
                combined.append(bottom or top or "")
        return combined

    def _xlsx_table_rows(
        self,
        cells: dict[tuple[int, int], str],
        header_row: int,
        start_col: int,
        end_col: int,
    ) -> tuple[list[list[str]], int]:
        max_row = max(row for row, _ in cells)
        rows: list[list[str]] = []
        empty_streak = 0
        cursor = header_row + 1
        max_empty_streak = 25
        while cursor <= max_row:
            values = [cells.get((cursor, col), "") for col in range(start_col, end_col + 1)]
            non_empty = sum(1 for value in values if clean_optional_text(value))
            if rows and self._xlsx_row_looks_like_header(values):
                break
            if non_empty == 0:
                empty_streak += 1
                if rows and empty_streak >= max_empty_streak:
                    break
            else:
                empty_streak = 0
                if self._xlsx_row_is_catalogue_data(values):
                    rows.append(values)
            cursor += 1
        return rows, cursor - 1

    def _xlsx_row_is_catalogue_data(self, values: list[str]) -> bool:
        cleaned = [clean_optional_text(value) or "" for value in values]
        non_empty = [value for value in cleaned if value]
        if not non_empty:
            return False
        if self._xlsx_row_looks_like_header(cleaned):
            return False
        joined = " ".join(non_empty)
        if len(non_empty) == 1 and re.search(
            r"(?i)\b(?:contact|email|phone|tel|website|address|notes?|terms?|bank|gst|vat|validity|disclaimer)\b",
            joined,
        ):
            return False
        return True

    def _xlsx_row_looks_like_header(self, values: list[str]) -> bool:
        if not self._is_catalogue_table_header(values):
            return False
        numeric_cells = sum(
            1
            for value in values
            if clean_optional_text(value) and re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
        )
        return numeric_cells == 0

    def _is_catalogue_table_header(self, values: list[str]) -> bool:
        cleaned = [value for value in values if clean_optional_text(value)]
        if len(cleaned) < 2:
            return False
        mapped = _header_map(cleaned)
        return _catalogue_header_has_required_shape(cleaned, mapped)

    def _format_xlsx_table(
        self,
        sheet_name: str,
        table_number: int,
        start_row: int,
        start_col: int,
        header: list[str],
        rows: list[list[str]],
    ) -> str:
        output = [
            f"[XLSX TABLE] Sheet: {sheet_name} Table: {table_number} Start: R{start_row}C{start_col}",
            self._markdown_table_row(header),
            self._markdown_table_row(["---"] * len(header)),
        ]
        output.extend(self._markdown_table_row(row) for row in rows)
        return "\n".join(output)

    def _markdown_table_row(self, cells: list[str]) -> str:
        escaped = [str(cell or "").replace("|", "\\|").strip() for cell in cells]
        return "| " + " | ".join(escaped) + " |"

    def _contiguous_number_bands(self, values: list[int], max_gap: int) -> list[list[int]]:
        if not values:
            return []
        bands: list[list[int]] = [[values[0]]]
        for value in values[1:]:
            if value - bands[-1][-1] <= max_gap:
                bands[-1].append(value)
            else:
                bands.append([value])
        return bands

    def _xlsx_cell_ref_to_indexes(self, ref: str) -> tuple[int, int]:
        match = re.fullmatch(r"([A-Z]+)(\d+)", ref or "", flags=re.IGNORECASE)
        if not match:
            return 0, 0
        col = 0
        for char in match.group(1).upper():
            col = col * 26 + (ord(char) - ord("A") + 1)
        return int(match.group(2)), col

    def _xml_root(self, raw_xml: bytes) -> Any:
        import xml.etree.ElementTree as ET

        return ET.fromstring(raw_xml)

    def _extract_with_anydoc(self, file_path: Path, fallback_format: str | None = None) -> str:
        try:
            from backend.app.pipeline.pipeline import process_document

            result = process_document(file_path)
            text = self._clean_anydoc_markdown(result.full_text())
            logger.info("Pipeline extracted %s characters from %s", len(text), file_path.name)
            return text
        except Exception:
            logger.exception("Pipeline extraction failed for %s", file_path.name)
            return ""

    def _clean_anydoc_markdown(self, text: str | None) -> str:
        if not text:
            return ""
        lines: list[str] = []
        previous_blank = False
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                if not previous_blank and lines:
                    lines.append("")
                previous_blank = True
                continue
            if re.match(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$", stripped):
                previous_blank = False
                continue
            if re.match(r"^\s*\[[^\]]*\]:\s*\S+\s*$", stripped):
                previous_blank = False
                continue
            lines.append(line)
            previous_blank = False
        return "\n".join(lines).strip()

    def _extract_image_text(self, file_path: Path, tenant_id: Any | None = None) -> str:
        from PIL import Image

        try:
            from backend.app.services.vision_extraction import extract_image_text_with_openrouter_vision

            vision_text = extract_image_text_with_openrouter_vision(
                file_path,
                source_name=file_path.name,
                db=self.db,
                tenant_id=tenant_id,
            )
            if vision_text:
                return "[OPENROUTER VISION OCR]\n" + vision_text

            grid_table_text = ""
            try:
                from backend.app.services.image_grid_extractor import extract_grid_table_from_image
                grid_result = extract_grid_table_from_image(file_path)
                if grid_result:
                    grid_table_text = "[RAPIDOCR TABLE OCR]\n" + grid_result.table_text
            except Exception:
                logger.debug("RapidOCR table extraction failed for %s; continuing with regular OCR", file_path.name, exc_info=True)

            from backend.app.services.ocr import recognize_image_to_text
            with Image.open(file_path) as image:
                page_text = recognize_image_to_text(image, file_path.name)

            texts: list[str] = []
            if grid_table_text:
                logger.info("RapidOCR table OCR extracted %s characters from image %s", len(grid_table_text), file_path.name)
                texts.append(grid_table_text)
            if page_text.strip():
                texts.append("[RAPIDOCR OCR]\n" + page_text.strip())
            text = "\n\n".join(dict.fromkeys(texts))
            logger.info("RapidOCR OCR extracted %s characters from image %s", len(text), file_path.name)
            return text
        except Exception as e:
            logger.exception("Error doing RapidOCR OCR on image %s: %s", file_path.name, e)
            return ""

    def _extract_text_from_file(self, file_path: Path, ext: str, tenant_id: Any | None = None) -> str:
        if ext == ".pdf":
            from backend.app.services.pdf_extract import extract_pdf_text
            return extract_pdf_text(file_path, use_vision_as_ocr_fallback=True, db=self.db, tenant_id=tenant_id)

        elif ext in (".xlsx", ".xls", ".xlsm", ".xltx", ".xltm"):
            return self._extract_spreadsheet_text(file_path, ext)

        elif ext == ".csv":
            return self._extract_spreadsheet_text(file_path, ext)

        elif ext == ".docx":
            return self._extract_docx_text(file_path)

        elif ext == ".doc":
            return self._extract_word_text(file_path, ext)

        elif ext in IMAGE_ATTACHMENT_EXTENSIONS:
            return self._extract_image_text(file_path, tenant_id=tenant_id)

        elif ext == ".txt":
            try:
                return file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""
        return ""

    def _extract_catalogue_text_from_file(
        self,
        file_path: Path,
        ext: str,
        existing_text: str,
        tenant_id: Any | None = None,
    ) -> str:
        if ext != ".pdf":
            return existing_text


        catalogue_text = extract_pdf_text(file_path, use_vision_for_images=True, db=self.db, tenant_id=tenant_id)
        return catalogue_text or existing_text

    def _extract_catalogue_items_from_image(
        self,
        file_path: Path,
        tenant_id: Any | None = None,
    ) -> list[ExtractedCatalogItem]:
        from backend.app.services.vision_extraction import extract_catalog_items_from_image_with_openrouter_vision

        items = extract_catalog_items_from_image_with_openrouter_vision(
            file_path,
            source_name=file_path.name,
            db=self.db,
            tenant_id=tenant_id,
        )
        normalized = [normalize_item(item) for item in items]
        return self._dedupe_extracted_items(normalized)

    def _catalogue_item_evidence_text(self, items: list[ExtractedCatalogItem]) -> str:
        lines = ["[OPENROUTER VISION JSON]"]
        for item in items:
            source = ""
            notes = item.notes or ""
            match = re.search(r"source\s*[:=]\s*['\"]?([^'\"]+)", notes, flags=re.IGNORECASE)
            if match:
                source = match.group(1).strip()
            lines.append(source or f"{item.ingredient_name} {item.price_per_unit or ''} {item.unit or ''}".strip())
        return "\n".join(line for line in lines if line)

    def _upload_file(self, file_path: Path, raw_email_id: str, mime_type: str) -> tuple[str, str]:
        safe_raw_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_email_id)
        clean_name = file_path.name.replace('\u00a0', '_').replace(' ', '_')
        safe_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', clean_name)
        object_path = f"{safe_raw_id}/{safe_filename}"
        ensure_supabase_storage_bucket(self.settings.supabase_storage_bucket)
        supabase = get_supabase()
        supabase.storage.from_(self.settings.supabase_storage_bucket).upload(
            object_path,
            file_path.read_bytes(),
            {"content-type": mime_type, "upsert": "true"},
        )
        return supabase.storage.from_(self.settings.supabase_storage_bucket).get_public_url(object_path), object_path

    def _delete_uploaded_files(self, object_paths: list[str]) -> None:
        if not object_paths:
            return
        try:
            get_supabase().storage.from_(self.settings.supabase_storage_bucket).remove(list(dict.fromkeys(object_paths)))
        except Exception:
            logger.warning("Failed to delete extracted email attachment objects", exc_info=True)

    def _imap_search_args_for_approach(self, approach: str, account: Any) -> tuple[str, ...]:
        """Return IMAP UID SEARCH args without relying on the user's read/unread state."""
        if approach == "approach_1":
            # The Suppliers label is the employee's explicit review boundary. A seen
            # message added to that label is still new to MediCORE until we log it.
            return ("UNDELETED", "ALL")

        created_at = getattr(account, "created_at", None)
        if not created_at:
            return ("UNDELETED", "ALL")

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return ("UNDELETED", "SINCE", created_at.strftime("%d-%b-%Y"))

    def preview_account_sync(self, account_id: UUID) -> dict:
        from backend.app.auth import decrypt_password
        from backend.app.models import CatalogEmail, EmailAccount, EmailSyncSetting

        account = self.db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
        if not account:
            return {"account_id": str(account_id), "error": "Email account not found."}

        try:
            password = decrypt_password(account.encrypted_password)
        except Exception as e:
            return {
                "account_id": str(account.id),
                "email_address": account.email_address,
                "error": f"Failed to decrypt app password: {str(e)}",
            }

        sync_setting = self.db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == account.user_id).first()
        approach = sync_setting.ingestion_approach if sync_setting else "approach_1"
        mailbox = "INBOX"

        try:
            safe_imap_host = validate_public_network_host(account.imap_host, field_name="imap_host")
            if account.imap_port != 993:
                raise ValueError("Only IMAP over SSL on port 993 is supported.")
            client = imaplib.IMAP4_SSL(safe_imap_host, account.imap_port, timeout=8)

            with client:
                client.login(account.email_address, password)

                if approach == "approach_1":
                    matched_mailbox = None
                    try:
                        status, mailboxes = client.list()
                        if status == "OK":
                            for mb in mailboxes:
                                mb_str = mb.decode("utf-8", errors="ignore")
                                match = re.search(r'"([^"]+)"\s*$', mb_str)
                                mb_name = match.group(1) if match else mb_str.split()[-1]
                                mb_name_lower = mb_name.strip().lower()
                                if (
                                    mb_name_lower in ("supplier", "suppliers")
                                    or mb_name_lower.endswith("/supplier")
                                    or mb_name_lower.endswith("/suppliers")
                                ):
                                    matched_mailbox = mb_name.strip()
                                    break
                    except Exception:
                        matched_mailbox = None
                    mailbox = matched_mailbox or "suppliers"

                status, _ = client.select(mailbox)
                if status != "OK":
                    return {
                        "account_id": str(account.id),
                        "email_address": account.email_address,
                        "approach": approach,
                        "mailbox": mailbox,
                        "error": f"Mailbox '{mailbox}' could not be selected.",
                    }

                search_args = self._imap_search_args_for_approach(approach, account)
                _, message_ids = client.uid("search", None, *search_args)
                ids = [msg_id.decode() for msg_id in (message_ids[0].split() if message_ids and message_ids[0] else [])]

            account_prefix = f"{account.id}:"
            logged_rows = self.db.query(CatalogEmail.raw_email_id, CatalogEmail.processing_status).filter(
                CatalogEmail.raw_email_id.like(f"{account_prefix}%")
            ).all()
            logged_raw_ids = {
                self._raw_email_base_id(raw_email_id, account.id)
                for raw_email_id, status in logged_rows
                if self._should_skip_logged_email(status)
            }
            candidate_raw_ids = [f"{account.id}:{mailbox}:{msg_id}" for msg_id in ids]
            new_candidate_count = len([raw_id for raw_id in candidate_raw_ids if raw_id not in logged_raw_ids])

            return {
                "account_id": str(account.id),
                "email_address": account.email_address,
                "approach": approach,
                "mailbox": mailbox,
                "search": " ".join(search_args),
                "candidate_count": len(ids),
                "already_logged_count": len(candidate_raw_ids) - new_candidate_count,
                "new_candidate_count": new_candidate_count,
            }
        except Exception as e:
            logger.exception("Failed IMAP sync preview for account %s", account.email_address)
            return {
                "account_id": str(account.id),
                "email_address": account.email_address,
                "approach": approach,
                "mailbox": mailbox,
                "error": str(e),
            }

    def _migrate_legacy_account_data(self, account_id: UUID, user_id: UUID) -> int:
        """Move only this mailbox's legacy shared records into its owner namespace.

        Older releases stored employee imports under the inviting admin's
        tenant. The raw email ID includes the immutable EmailAccount ID, which
        gives us a reliable ownership key without guessing from sender data.
        """
        account_prefix = f"{account_id}:"
        legacy_emails = (
            self.db.query(CatalogEmail)
            .filter(
                CatalogEmail.raw_email_id.like(f"{account_prefix}%"),
                CatalogEmail.tenant_id != user_id,
            )
            .all()
        )
        if not legacy_emails:
            return 0

        supplier_by_legacy_id: dict[Any, Supplier] = {}
        moved = 0
        try:
            for catalog_email in legacy_emails:
                # A supplier may also be used by another employee in the old
                # shared tenant. Clone/reuse it in the new namespace instead
                # of changing its tenant and moving someone else's records.
                target_supplier = supplier_by_legacy_id.get(catalog_email.supplier_id)
                if target_supplier is None:
                    legacy_supplier = self.db.query(Supplier).filter(Supplier.id == catalog_email.supplier_id).first()
                    if not legacy_supplier:
                        logger.warning("Skipping legacy email %s because supplier %s is missing", catalog_email.id, catalog_email.supplier_id)
                        continue
                    target_supplier = (
                        self.db.query(Supplier)
                        .filter(Supplier.tenant_id == user_id, Supplier.email_domain == legacy_supplier.email_domain)
                        .first()
                    )
                    if target_supplier is None:
                        target_supplier = Supplier(
                            id=uuid4(),
                            tenant_id=user_id,
                            name=legacy_supplier.name,
                            email_domain=legacy_supplier.email_domain,
                            country=legacy_supplier.country or UNKNOWN_COUNTRY,
                            last_email_date=legacy_supplier.last_email_date,
                            certifications=legacy_supplier.certifications,
                        )
                        self.db.add(target_supplier)
                        self.db.flush()
                    supplier_by_legacy_id[catalog_email.supplier_id] = target_supplier

                duplicate = (
                    self.db.query(CatalogEmail.id)
                    .filter(
                        CatalogEmail.tenant_id == user_id,
                        CatalogEmail.raw_email_id == catalog_email.raw_email_id,
                    )
                    .first()
                )
                if duplicate:
                    logger.warning("Skipping legacy email %s because it already exists in user namespace", catalog_email.raw_email_id)
                    continue

                self.db.query(CatalogItem).filter(CatalogItem.catalog_email_id == catalog_email.id).update(
                    {CatalogItem.tenant_id: user_id, CatalogItem.supplier_id: target_supplier.id},
                    synchronize_session=False,
                )
                catalog_email.tenant_id = user_id
                catalog_email.supplier_id = target_supplier.id
                moved += 1

            if moved:
                self.db.commit()
                logger.info("Migrated %s legacy catalogue email(s) for account %s into user %s", moved, account_id, user_id)
            return moved
        except Exception:
            self.db.rollback()
            logger.exception("Failed to migrate legacy catalogue data for account %s", account_id)
            return 0

    def poll_account_inbox(
        self,
        account_id: UUID,
        force_retry_failed: bool = False,
        retry_skipped: bool = False,
        retry_failed_once: bool = False,
    ) -> int:
        from backend.app.models import CatalogEmail, EmailAccount, EmailFilter
        from backend.app.auth import decrypt_password

        account = self.db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
        if not account:
            logger.error("EmailAccount %s not found for polling", account_id)
            return 0

        account_user_id = account.user_id
        self._migrate_legacy_account_data(account_id, account_user_id)
        account_email_address = account.email_address
        account_imap_host = account.imap_host
        account_imap_port = account.imap_port
        account_encrypted_password = account.encrypted_password

        # Each connected mailbox is its own data boundary. Profile.tenant_id
        # only groups employees for administrative management.
        active_tenant_id = account_user_id

        if force_retry_failed:
            try:
                account_prefix = f"{account_id}:"
                self.db.query(CatalogEmail).filter(
                    CatalogEmail.raw_email_id.like(f"{account_prefix}%")
                ).filter(
                    (CatalogEmail.processing_status.like("failed%")) |
                    (CatalogEmail.processing_status.like("error%")) |
                    (CatalogEmail.processing_status.is_(None))
                ).delete(synchronize_session=False)
                self.db.commit()
                logger.info("Cleared failed/error catalog email logs to force retry for account %s", account_email_address)
            except Exception as e:
                self.db.rollback()
                logger.error("Failed to clean up failed catalog logs for retry: %s", e)

        if retry_skipped:
            try:
                account_prefix = f"{account_id}:"
                retried = self.db.query(CatalogEmail).filter(
                    CatalogEmail.raw_email_id.like(f"{account_prefix}%"),
                    CatalogEmail.processing_status.in_(["skipped", "ignored: no supplier catalogue intent"]),
                ).delete(synchronize_session=False)
                self.db.commit()
                logger.info(
                    "Cleared %s skipped catalog email log(s) for manual retry on account %s",
                    retried,
                    account_email_address,
                )
            except Exception as e:
                self.db.rollback()
                logger.error("Failed to clear skipped catalog logs for retry: %s", e)

        # Decrypt password securely
        try:
            password = decrypt_password(account_encrypted_password)
        except Exception as e:
            logger.error("Failed to decrypt password for email account %s: %s", account_id, e)
            self.db.query(EmailAccount).filter(EmailAccount.id == account_id).update(
                {
                    EmailAccount.sync_status: "error",
                    EmailAccount.sync_error_msg: f"Failed to decrypt app password: {str(e)}",
                },
                synchronize_session=False,
            )
            self.db.commit()
            return 0

        try:
            account_imap_host = validate_public_network_host(account_imap_host, field_name="imap_host")
            if account_imap_port != 993:
                raise ValueError("Only IMAP over SSL on port 993 is supported.")
        except Exception as e:
            logger.warning("Rejected unsafe IMAP settings for email account %s: %s", account_id, e)
            self.db.query(EmailAccount).filter(EmailAccount.id == account_id).update(
                {
                    EmailAccount.sync_status: "error",
                    EmailAccount.sync_error_msg: "Stored IMAP settings are invalid. Reconnect the mailbox using a public SSL IMAP host on port 993.",
                },
                synchronize_session=False,
            )
            self.db.commit()
            return 0

        # Run IMAP connection
        processed = 0
        from backend.app.services.terminal_sync_status import sync_notifier
        sync_notifier.start_sync_banner(mode="Frontend Email Sync", target=account_email_address)
        sync_notifier.notify_fetching_emails(account_email_address)

        try:
            logger.info("Connecting to IMAP for %s at %s:%s", account_email_address, account_imap_host, account_imap_port)
            client = imaplib.IMAP4_SSL(account_imap_host, account_imap_port, timeout=30)

            with client:
                client.login(account_email_address, password)

                # Fetch filters and global sync settings
                active_filter = self.db.query(EmailFilter).filter(EmailFilter.email_account_id == account_id).first()
                from backend.app.models import EmailSyncSetting
                sync_setting = self.db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == account_user_id).first()
                approach = sync_setting.ingestion_approach if sync_setting else "approach_1"
                pending_email_ids: set[str] = set()
                ignored_email_ids: set[str] = set()
                ignored_email_fingerprints: set[str] = set()
                ignored_email_keys: set[str] = set()
                trusted_suppliers = sync_setting.trusted_suppliers if sync_setting else ""
                if sync_setting:
                    try:
                        cleaned_pending_approvals = filter_trusted_pending_approvals(
                            sync_setting.pending_approvals,
                            trusted_suppliers,
                        )
                        if cleaned_pending_approvals != (sync_setting.pending_approvals or "[]"):
                            sync_setting.pending_approvals = cleaned_pending_approvals
                            self.db.commit()
                        approval_items = json.loads(cleaned_pending_approvals)
                        pending_email_ids = {
                            str(item.get("email_id"))
                            for item in approval_items
                            if isinstance(item, dict) and item.get("email_id") and not item.get("ignored")
                        }
                        ignored_email_ids = {
                            str(item.get("email_id"))
                            for item in approval_items
                            if isinstance(item, dict) and item.get("email_id") and item.get("ignored")
                        }
                        ignored_email_fingerprints = {
                            str(item.get("fingerprint"))
                            for item in approval_items
                            if isinstance(item, dict) and item.get("fingerprint") and item.get("ignored")
                        }
                        ignored_email_keys = {
                            "|".join(
                                [
                                    str(item.get("sender") or "").strip().lower(),
                                    str(item.get("subject") or "").strip().lower(),
                                    str(item.get("date") or "").strip(),
                                ]
                            )
                            for item in approval_items
                            if isinstance(item, dict) and item.get("ignored")
                        }
                    except Exception:
                        pending_email_ids = set()
                        ignored_email_ids = set()
                        ignored_email_fingerprints = set()
                        ignored_email_keys = set()

                mailbox = "INBOX"
                if approach == "approach_1":
                    matched_mailbox = None
                    try:
                        status, mailboxes = client.list()
                        if status == "OK":
                            for mb in mailboxes:
                                mb_str = mb.decode("utf-8", errors="ignore")
                                import re
                                match = re.search(r'"([^"]+)"\s*$', mb_str)
                                if not match:
                                    mb_name = mb_str.split()[-1]
                                else:
                                    mb_name = match.group(1)

                                mb_name_lower = mb_name.strip().lower()
                                if mb_name_lower in ("supplier", "suppliers") or mb_name_lower.endswith("/supplier") or mb_name_lower.endswith("/suppliers"):
                                    matched_mailbox = mb_name.strip()
                                    break
                    except Exception as e:
                        logger.warning("Error listing mailboxes: %s", e)

                    if matched_mailbox:
                        mailbox = matched_mailbox
                        logger.info("Found matching supplier mailbox: %s", mailbox)
                    else:
                        mailbox = "suppliers"

                try:
                    status, _ = client.select(mailbox)
                    if status != "OK":
                        raise imaplib.IMAP4.error(f"Select failed for {mailbox}")
                except imaplib.IMAP4.error:
                    if approach == "approach_1":
                        fallbacks = ["suppliers", "supplier"]
                        selected = False
                        for fb in fallbacks:
                            if fb == mailbox:
                                continue
                            try:
                                status_fb, _ = client.select(fb)
                                if status_fb == "OK":
                                    logger.warning("Mailbox %s selection failed. Fell back to %s", mailbox, fb)
                                    mailbox = fb
                                    selected = True
                                    break
                            except imaplib.IMAP4.error:
                                pass
                        if not selected:
                            msg = (
                                "The 'Suppliers' label was not found in your mailbox. "
                                "Create it and move supplier emails into it, or switch to trusted supplier approval mode in Email Settings."
                            )
                            logger.warning("Supplier label mailbox was not found for account %s; sync stopped", account_email_address)
                            account.sync_status = "error"
                            account.sync_error_msg = msg
                            self.db.commit()
                            return 0
                    elif mailbox != "INBOX":
                        fallbacks = ["INBOX"]
                        selected = False
                        for fb in fallbacks:
                            try:
                                status_fb, _ = client.select(fb)
                                if status_fb == "OK":
                                    logger.warning("Mailbox %s selection failed. Fell back to %s", mailbox, fb)
                                    mailbox = fb
                                    selected = True
                                    break
                            except imaplib.IMAP4.error:
                                pass
                        if not selected:
                            raise RuntimeError("Failed to select INBOX")
                    else:
                        raise

                # Search by UID so stored message IDs remain stable even when mailbox sequence numbers change.
                search_args = self._imap_search_args_for_approach(approach, account)
                _, message_ids = client.uid("search", None, *search_args)
                ids = message_ids[0].split() if message_ids and message_ids[0] else []
                # Process newest first
                ids.reverse()
                logger.info(
                    "Account %s has %s candidate messages in %s (criteria: %s)",
                    account_email_address,
                    len(ids),
                    mailbox,
                    " ".join(search_args),
                )

                # Fetch already processed email IDs cache to optimize DB lookup.
                skipped_logged_email_ids = set()
                retryable_logged_email_ids = set()
                from backend.app.models import CatalogEmail
                res = self.db.query(CatalogEmail).filter(CatalogEmail.tenant_id == active_tenant_id).all()
                exhausted_retry_count = 0
                for email_row in res:
                    raw_stored_id = email_row.raw_email_id
                    status = email_row.processing_status
                    base_id = self._raw_email_base_id(raw_stored_id, account_id)
                    if retry_failed_once and self._is_retryable_logged_email(status):
                        current_retry_count = int(email_row.retry_count or 0)
                        if current_retry_count < MAX_EMAIL_RETRY_ATTEMPTS:
                            retryable_logged_email_ids.add(base_id)
                            continue
                        terminal_status = self._terminal_retry_status(status)
                        if email_row.processing_status != terminal_status:
                            email_row.processing_status = terminal_status
                            exhausted_retry_count += 1
                    if self._should_skip_logged_email(status):
                        skipped_logged_email_ids.add(base_id)
                if exhausted_retry_count:
                    self.db.commit()
                    logger.info(
                        "Marked %s exhausted failed/partial email(s) as permanent for account %s",
                        exhausted_retry_count,
                        account_email_address,
                    )

                trusted_initial_import_counts: dict[str, int] = defaultdict(int)
                for msg_id in ids:
                    msg_id_str = msg_id.decode()
                    raw_id_str = f"{account_id}:{mailbox}:{msg_id_str}"
                    if raw_id_str in skipped_logged_email_ids:
                        continue
                    should_retry_logged_email = raw_id_str in retryable_logged_email_ids
                    if raw_id_str in pending_email_ids:
                        continue

                    try:
                        logger.info("Fetching message id=%s for account %s", raw_id_str, account_email_address)
                        _, data = client.uid("fetch", msg_id, "(BODY.PEEK[])")
                        if not data or not isinstance(data[0], tuple):
                            continue
                        if len(data[0][1]) > MAX_DOCUMENT_BYTES:
                            logger.warning("Skipping email id=%s because raw RFC822 payload exceeds 30 MB", raw_id_str)
                            self._create_skipped_email_record(raw_id_str, "unknown@supplier.com", "Unknown", "Oversized email", "ignored: email exceeds 30 MB", active_tenant_id)
                            continue

                        message = email.message_from_bytes(data[0][1])

                        # Apply keyword / attachment filters
                        email_date = self._message_received_at(message)
                        display_name, sender = self._extract_sender(message)
                        subject = message.get("Subject") or ""
                        email_fingerprint = self._message_fingerprint(message, sender, subject, email_date)
                        domain = get_supplier_domain(sender)
                        is_trusted = trusted_sender_matches(sender, trusted_suppliers)
                        supplier_exists = False
                        if approach == "approach_2" and sync_setting:
                            supplier_exists = (
                                self.db.query(Supplier.id)
                                .join(CatalogEmail, CatalogEmail.supplier_id == Supplier.id)
                                .join(CatalogItem, CatalogItem.catalog_email_id == CatalogEmail.id)
                                .filter(
                                    Supplier.tenant_id == active_tenant_id,
                                    Supplier.email_domain == domain,
                                    CatalogEmail.processing_status.in_(["completed", "partial"]),
                                )
                                .first()
                                is not None
                            )
                            if is_trusted and not supplier_exists:
                                if trusted_initial_import_counts[domain] >= 5:
                                    logger.info("Skipping email id=%s because trusted supplier initial import is limited to the latest 5 messages", raw_id_str)
                                    self._create_skipped_email_record(
                                        raw_id_str,
                                        sender,
                                        display_name,
                                        subject,
                                        "ignored: outside trusted supplier initial import window",
                                        active_tenant_id,
                                        email_date,
                                    )
                                    self._mark_seen(client, msg_id)
                                    continue
                                trusted_initial_import_counts[domain] += 1

                        labels = message.get("X-Gmail-Labels", "")
                        list_unsubscribe = message.get("List-Unsubscribe", "")
                        precedence = message.get("Precedence", "")

                        # Collect all attachments and email body text
                        attachments = self._collect_attachments(message)
                        body_text = self._get_email_body_text(message)

                        if self._is_irrelevant_or_marketing_email(
                            message=message,
                            sender=sender,
                            subject=subject,
                            body_text=body_text,
                            labels=labels,
                            list_unsubscribe=list_unsubscribe,
                            precedence=precedence,
                        ):
                            logger.info("Skipping non-supplier/marketing email id=%s from=%s subject=%r", raw_id_str, sender, subject)
                            self._create_skipped_email_record(
                                raw_id_str,
                                sender,
                                display_name,
                                subject,
                                "skipped: newsletter or promotional email",
                                active_tenant_id,
                                email_date,
                                body_text,
                            )
                            self._mark_seen(client, msg_id)
                            continue

                        # Build parse targets
                        parse_targets = []
                        for att in attachments:
                            parse_targets.append({
                                "name": att["filename"],
                                "payload": att["payload"],
                                "ext": att["ext"],
                                "mime_type": att["mime_type"],
                                "is_body": False
                            })

                        if body_text.strip():
                            parse_targets.append({
                                "name": "email_body.txt",
                                "payload": body_text.encode("utf-8"),
                                "ext": ".txt",
                                "mime_type": "text/plain",
                                "is_body": True
                            })

                        # Filter: Require attachment
                        if active_filter and active_filter.require_attachment and not attachments:
                            logger.info("Skipping email id=%s because attachment is required but none found", raw_id_str)
                            self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: attachment required", active_tenant_id, email_date, body_text)
                            self._mark_seen(client, msg_id)
                            continue

                        if active_filter:
                            sender_terms = self._csv_terms(active_filter.sender_keywords)
                            if sender_terms and not self._sender_matches_any(sender, display_name, sender_terms):
                                logger.info("Skipping email id=%s because sender filter did not match", raw_id_str)
                                self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: sender filter", active_tenant_id, email_date, body_text)
                                self._mark_seen(client, msg_id)
                                continue

                            subject_terms = self._csv_terms(active_filter.subject_keywords)
                            if subject_terms and not self._text_matches_any(subject, subject_terms):
                                logger.info("Skipping email id=%s because subject filter did not match", raw_id_str)
                                self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: subject filter", active_tenant_id, email_date, body_text)
                                self._mark_seen(client, msg_id)
                                continue

                        if not self._has_supplier_catalogue_intent(subject, body_text, attachments):
                            logger.info("Skipping email id=%s because no supplier catalogue intent was detected", raw_id_str)
                            self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: no supplier catalogue intent", active_tenant_id, email_date, body_text)
                            self._mark_seen(client, msg_id)
                            continue

                        # Check Ingestion Approach 2
                        if approach == "approach_2" and sync_setting:
                            email_approval_key = "|".join(
                                [
                                    sender.strip().lower(),
                                    subject.strip().lower(),
                                    email_date.isoformat(),
                                ]
                            )
                            if not is_trusted and (
                                raw_id_str in ignored_email_ids
                                or email_fingerprint in ignored_email_fingerprints
                                or email_approval_key in ignored_email_keys
                            ):
                                logger.info("Skipping email id=%s because user denied processing previously", raw_id_str)
                                self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: denied by user", active_tenant_id, email_date, body_text)
                                self._mark_seen(client, msg_id)
                                continue

                            if not is_trusted and not supplier_exists:
                                if parse_targets:
                                    # New supplier alert! Add to pending_approvals and DO NOT mark read
                                    try:
                                        pending_list = json.loads(sync_setting.pending_approvals or "[]")
                                    except Exception:
                                        pending_list = []

                                    if not any(
                                        isinstance(item, dict)
                                        and (item.get("email_id") == raw_id_str or item.get("fingerprint") == email_fingerprint)
                                        for item in pending_list
                                    ):
                                        pending_list.append({
                                            "email_id": raw_id_str,
                                            "fingerprint": email_fingerprint,
                                            "sender": sender,
                                            "supplier_name": display_name or sender,
                                            "subject": subject,
                                            "date": email_date.isoformat(),
                                            "reason": "Supplier approval required",
                                        })
                                        sync_setting.pending_approvals = json.dumps(pending_list)
                                        pending_email_ids.add(raw_id_str)
                                        self.db.commit()
                                        logger.info("Added email id=%s to pending_approvals for %s", raw_id_str, sender)
                                    continue
                                else:
                                    # Has no supported supplier content, skip and mark as seen
                                    logger.info("Skipping non-supplier email id=%s from=%s subject=%r", raw_id_str, sender, subject)
                                    self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: no parseable supplier content", active_tenant_id, email_date, body_text)
                                    self._mark_seen(client, msg_id)
                                    continue

                        # Process message if we have parse targets and matched everything
                        if parse_targets:
                            try:
                                if should_retry_logged_email:
                                    self._mark_email_retry_attempt(raw_id_str, active_tenant_id)
                                processed += self._process_message(
                                    message,
                                    raw_email_id=raw_id_str,
                                    parse_targets=parse_targets,
                                    tenant_id=active_tenant_id,
                                    allow_logged_retry=should_retry_logged_email,
                                )
                                self._restore_unseen_after_processing(client, msg_id)
                            except Exception as pe:
                                logger.exception("Failed processing email payload for raw_email_id=%s", raw_id_str)
                                self._create_failed_email_record(raw_id_str, sender, display_name, subject, f"Failed: {str(pe)}", tenant_id=active_tenant_id, email_date=email_date, body_text=body_text)

                        else:
                            logger.info("Skipping email id=%s because it had no parseable payload", raw_id_str)
                            self._create_skipped_email_record(raw_id_str, sender, display_name, subject, "ignored: no parseable payload", active_tenant_id, email_date, body_text)
                            self._mark_seen(client, msg_id)

                    except Exception as inner_e:
                        logger.exception("Error processing email msg_id=%s", msg_id)
                        try:
                            self._create_failed_email_record(raw_id_str, "unknown@supplier.com", "Unknown", "Extraction Failure", f"Failed: {str(inner_e)}", tenant_id=active_tenant_id)
                        except Exception:
                            pass

                # Update status
                self.db.query(EmailAccount).filter(EmailAccount.id == account_id).update(
                    {
                        EmailAccount.sync_status: "ok",
                        EmailAccount.sync_error_msg: None,
                        EmailAccount.last_synced_at: datetime.now(UTC),
                    },
                    synchronize_session=False,
                )
                self.db.commit()
                logger.info("Successfully finished polling for %s; processed %s", account_email_address, processed)
                from backend.app.services.terminal_sync_status import sync_notifier
                sync_notifier.sync_complete_summary(
                    emails_checked=1,
                    pdfs_processed=processed,
                    total_items_extracted=processed,
                    gmft_tables_found=processed,
                )

        except Exception as e:
            logger.exception("Error polling account %s", account_email_address)
            self.db.rollback()
            try:
                self.db.query(EmailAccount).filter(EmailAccount.id == account_id).update(
                    {
                        EmailAccount.sync_status: "error",
                        EmailAccount.sync_error_msg: f"IMAP connection failed: {str(e)}",
                    },
                    synchronize_session=False,
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                logger.exception("Failed to persist polling error status for account %s", account_id)

        return processed

    def _create_failed_email_record(
        self,
        raw_email_id: str,
        sender: str,
        display_name: str,
        subject: str,
        error_msg: str,
        tenant_id: Any,
        email_date: datetime | None = None,
        body_text: str | None = None,
    ) -> None:
        try:
            self.db.rollback()
            from backend.app.models import CatalogEmail
            from uuid import uuid4
            public_error = public_processing_failure(error_msg)

            existing = (
                self.db.query(CatalogEmail)
                .filter(CatalogEmail.raw_email_id == raw_email_id)
                .filter(CatalogEmail.tenant_id == tenant_id)
                .first()
            )
            if existing:
                existing.processing_status = f"failed: {public_error}"[:50]
                existing.pdf_url = None
                existing.body_preview = self._body_preview(body_text)
                if email_date:
                    existing.received_at = email_date
                self.db.commit()
                return

            supplier = self._upsert_supplier(sender, display_name=display_name, tenant_id=tenant_id)

            catalog_email = CatalogEmail(
                id=uuid4(),
                tenant_id=tenant_id or supplier.tenant_id,
                supplier_id=supplier.id,
                raw_email_id=raw_email_id,
                subject=subject,
                pdf_url=None,
                body_preview=self._body_preview(body_text),
                received_at=email_date or datetime.now(UTC),
                processing_status=f"failed: {public_error}"[:50],
            )
            self.db.add(catalog_email)
            self.db.commit()
            logger.info("Saved sync fallback/failed email record for id=%s: %s", raw_email_id, error_msg)
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to write fallback/failed email record to DB: %s", e)

    def _create_skipped_email_record(
        self,
        raw_email_id: str,
        sender: str,
        display_name: str,
        subject: str,
        reason: str,
        tenant_id: Any,
        email_date: datetime | None = None,
        body_text: str | None = None,
    ) -> None:
        try:
            existing = (
                self.db.query(CatalogEmail)
                .filter(CatalogEmail.raw_email_id == raw_email_id)
                .filter(CatalogEmail.tenant_id == tenant_id)
                .first()
            )
            if existing:
                if existing.body_preview:
                    existing.body_preview = None
                    self.db.commit()
                return

            supplier = self._upsert_supplier(sender, display_name=display_name, tenant_id=tenant_id)
            self.db.add(
                CatalogEmail(
                    id=uuid4(),
                    tenant_id=tenant_id or supplier.tenant_id,
                    supplier_id=supplier.id,
                    raw_email_id=raw_email_id,
                    subject=subject,
                    pdf_url=None,
                    body_preview=None,
                    received_at=email_date or datetime.now(UTC),
                    processing_status=reason[:50],
                )
            )
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to write skipped email tombstone to DB: %s", e)

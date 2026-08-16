import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.services.email_ingestion import EmailIngestionService
from backend.app.tasks import poll_inbox
from backend.app.auth import get_current_admin, get_current_user
from backend.app.api.email_accounts import queue_email_account_sync

router = APIRouter()
logger = logging.getLogger(__name__)


class ImapCredentials(BaseModel):
    email: str
    app_password: str = Field(min_length=1)
    mailbox: str = "INBOX"


@router.get("/imap-preview")
def imap_preview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> dict:
    return EmailIngestionService(db).preview_imap_inbox()


@router.post("/imap-preview-with-credentials")
def imap_preview_with_credentials(
    payload: ImapCredentials,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> dict:
    return EmailIngestionService(db).preview_imap_inbox(
        imap_username=payload.email,
        imap_password=payload.app_password,
        imap_mailbox=payload.mailbox,
    )


@router.post("/poll-now")
def poll_now(current_user: dict = Depends(get_current_admin)) -> dict[str, str]:
    task = poll_inbox.delay()
    return {"status": "queued", "task_id": task.id}


@router.post("/poll-now-sync")
def poll_now_sync(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> dict[str, int]:
    processed = EmailIngestionService(db).poll_imap_inbox()
    return {"processed": processed}


@router.post("/poll-now-sync-user")
def poll_now_sync_user(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    from uuid import UUID
    import json
    from backend.app.models import EmailAccount, EmailSyncSetting
    user_uuid = UUID(current_user["id"])
    accounts = db.query(EmailAccount).filter(EmailAccount.user_id == user_uuid).all()

    task_ids: list[str] = []
    previews = []
    preview_service = EmailIngestionService(db)
    for account in accounts:
        previews.append(preview_service.preview_account_sync(account.id))
        account.sync_status = "pending"
        account.sync_error_msg = None

    # Commit before dispatching. A fast worker may finish immediately and write
    # "ok"; committing "pending" after dispatch would overwrite that result.
    db.commit()

    queue_errors: list[dict[str, str]] = []
    for account in accounts:
        try:
            task_ids.append(queue_email_account_sync(account.id))
        except Exception:
            logger.exception("Failed to queue email sync for account_id=%s", account.id)
            account.sync_status = "error"
            account.sync_error_msg = "Could not queue email sync. Check the Celery worker and Redis connection."
            db.commit()
            queue_errors.append({
                "account_id": str(account.id),
                "message": account.sync_error_msg,
            })

    queued_accounts = len(task_ids)
    sync_setting = db.query(EmailSyncSetting).filter(EmailSyncSetting.user_id == user_uuid).first()
    pending_count = 0
    if sync_setting:
        try:
            pending_items = json.loads(sync_setting.pending_approvals or "[]")
            pending_count = len([
                item for item in pending_items
                if isinstance(item, dict) and not item.get("ignored")
            ])
        except Exception:
            pending_count = 0

    return {
        "status": "queued" if queued_accounts else ("error" if accounts else "no_accounts"),
        "queued_accounts": queued_accounts,
        "failed_accounts": len(queue_errors),
        "queue_errors": queue_errors,
        "task_ids": task_ids,
        "processed": 0,
        "pending_approvals": pending_count,
        "candidate_messages": sum(int(item.get("candidate_count") or 0) for item in previews),
        "new_candidate_messages": sum(int(item.get("new_candidate_count") or 0) for item in previews),
        "previews": previews,
    }


@router.post("/poll-now-sync-with-credentials")
def poll_now_sync_with_credentials(
    payload: ImapCredentials,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> dict[str, int]:
    processed = EmailIngestionService(db).poll_imap_inbox(
        imap_username=payload.email,
        imap_password=payload.app_password,
        imap_mailbox=payload.mailbox,
    )
    return {"processed": processed}


@router.post("/reprocess-empty")
def reprocess_empty(
    db: Session = Depends(get_db),
    force: bool = Query(False),
    current_user: dict = Depends(get_current_admin),
) -> dict:
    try:
        processed = EmailIngestionService(db).reprocess_empty_catalog_emails(force=force)
        return {"processed": processed, "error": None}
    except Exception:
        db.rollback()
        return {"processed": 0, "error": "Reprocessing failed."}

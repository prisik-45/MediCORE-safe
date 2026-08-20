import logging

from backend.app.celery_app import celery_app
from backend.app.db import SessionLocal
from backend.app.services.email_ingestion import EmailIngestionService

logger = logging.getLogger(__name__)


@celery_app.task(name="backend.app.tasks.poll_inbox")
def poll_inbox(force: bool = False, retry_skipped: bool = False) -> dict:
    from datetime import datetime, UTC
    from backend.app.models import EmailAccount, EmailSyncSetting, Profile
    logger.info("Starting batch scheduled IMAP inbox poll task")
    processed_total = 0
    checked_total = 0
    with SessionLocal() as db:
        service = EmailIngestionService(db)
        now = datetime.now(UTC)
        accounts = db.query(EmailAccount).all()
        settings_by_user = {
            row.user_id: row
            for row in db.query(EmailSyncSetting).filter(
                EmailSyncSetting.user_id.in_([account.user_id for account in accounts])
            ).all()
        } if accounts else {}
        active_user_ids = {
            row.id
            for row in db.query(Profile.id).filter(
                Profile.id.in_([account.user_id for account in accounts]),
                Profile.status == "Active",
            ).all()
        } if accounts else set()

        for account in accounts:
            if active_user_ids and account.user_id not in active_user_ids:
                continue

            checked_total += 1
            sync_setting = settings_by_user.get(account.user_id)
            interval = max(int(sync_setting.poll_interval_minutes), 5) if sync_setting else 15

            should_sync = False
            if account.last_synced_at is None:
                should_sync = True
            else:
                last_synced_at = account.last_synced_at
                if last_synced_at.tzinfo is None:
                    last_synced_at = last_synced_at.replace(tzinfo=UTC)
                diff_seconds = (now - last_synced_at).total_seconds()
                if diff_seconds >= (interval * 60):
                    should_sync = True

            if should_sync or force:
                reason = "forced manual sync" if force and not should_sync else f"due for sync (interval={interval} min)"
                logger.info("Account %s is %s", account.email_address, reason)
                processed_total += service.poll_account_inbox(
                    account.id,
                    retry_skipped=retry_skipped,
                )

    logger.info("Finished batch IMAP inbox poll task; checked=%s processed total=%s", checked_total, processed_total)
    return {"checked": checked_total, "processed": processed_total}


@celery_app.task(name="backend.app.tasks.poll_email_account")
def poll_email_account(account_id: str) -> dict:
    from uuid import UUID
    logger.info("Starting IMAP poll task for account_id=%s", account_id)
    with SessionLocal() as db:
        service = EmailIngestionService(db)
        processed = service.poll_account_inbox(UUID(account_id))
    logger.info("Finished IMAP poll task for account_id=%s; processed=%s", account_id, processed)
    return {"processed": processed}


@celery_app.task(name="backend.app.tasks.process_gmail_notification")
def process_gmail_notification(payload: dict) -> dict:
    with SessionLocal() as db:
        service = EmailIngestionService(db)
        processed = service.process_gmail_push_payload(payload)
    return {"processed": processed}


@celery_app.task(name="backend.app.tasks.send_transactional_email")
def send_transactional_email(to_email: str, subject: str, html_content: str) -> bool:
    from backend.app.services.email_sender import send_transactional_email
    return send_transactional_email(to_email, subject, html_content)




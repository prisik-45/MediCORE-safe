import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from redis import Redis
from sqlalchemy import or_
from sqlalchemy.orm import aliased

from backend.app.celery_app import celery_app
from backend.app.config import get_settings
from backend.app.db import SessionLocal
from backend.app.models import EmailAccount, EmailSyncSetting, Profile
from backend.app.services.email_ingestion import EmailIngestionService

logger = logging.getLogger(__name__)

POLL_LOCK_TTL_SECONDS = 30 * 60


def _active_poll_user_ids(db, user_ids: list[UUID]) -> set[UUID]:
    if not user_ids:
        return set()
    AdminProfile = aliased(Profile)
    rows = (
        db.query(Profile.id)
        .outerjoin(AdminProfile, Profile.tenant_id == AdminProfile.id)
        .filter(
            Profile.id.in_(user_ids),
            Profile.status == "Active",
            or_(AdminProfile.id.is_(None), AdminProfile.status == "Active"),
        )
        .all()
    )
    return {row.id for row in rows}


def _poll_lock_client() -> Redis:
    return Redis.from_url(
        get_settings().queue_url,
        socket_connect_timeout=3,
        socket_timeout=10,
        decode_responses=True,
    )


def _acquire_poll_lock(account_id: str) -> tuple[Redis, str, str] | None:
    key = f"lock:poll:{account_id}"
    token = str(uuid4())
    try:
        client = _poll_lock_client()
        if client.set(key, token, nx=True, ex=POLL_LOCK_TTL_SECONDS):
            return client, key, token
    except Exception:
        logger.exception("Could not acquire poll lock for account_id=%s", account_id)
    return None


def _release_poll_lock(lock: tuple[Redis, str, str] | None) -> None:
    if not lock:
        return
    client, key, token = lock
    try:
        if client.get(key) == token:
            client.delete(key)
    except Exception:
        logger.warning("Could not release poll lock %s", key, exc_info=True)


@celery_app.task(name="backend.app.tasks.poll_inbox")
def poll_inbox(force: bool = False, retry_skipped: bool = False) -> dict:
    logger.info("Starting scheduled IMAP inbox dispatcher")
    checked_total = 0
    queued_total = 0
    skipped_inactive = 0
    skipped_not_due = 0

    with SessionLocal() as db:
        now = datetime.now(UTC)
        accounts = db.query(EmailAccount).all()
        user_ids = [account.user_id for account in accounts]
        settings_by_user = (
            {
                row.user_id: row
                for row in db.query(EmailSyncSetting)
                .filter(EmailSyncSetting.user_id.in_(user_ids))
                .all()
            }
            if user_ids
            else {}
        )
        active_user_ids = _active_poll_user_ids(db, user_ids)

        for account in accounts:
            checked_total += 1
            if account.user_id not in active_user_ids:
                skipped_inactive += 1
                continue

            sync_setting = settings_by_user.get(account.user_id)
            interval = max(int(sync_setting.poll_interval_minutes), 5) if sync_setting else 15

            should_sync = account.last_synced_at is None
            if account.last_synced_at is not None:
                last_synced_at = account.last_synced_at
                if last_synced_at.tzinfo is None:
                    last_synced_at = last_synced_at.replace(tzinfo=UTC)
                should_sync = (now - last_synced_at).total_seconds() >= interval * 60

            if not (should_sync or force):
                skipped_not_due += 1
                continue

            poll_email_account.apply_async(
                args=[str(account.id)],
                kwargs={
                    "force_retry_failed": False,
                    "retry_skipped": retry_skipped,
                    "retry_failed_once": True,
                },
                retry=False,
            )
            queued_total += 1

    logger.info(
        "Finished scheduled IMAP dispatcher; checked=%s queued=%s skipped_inactive=%s skipped_not_due=%s",
        checked_total,
        queued_total,
        skipped_inactive,
        skipped_not_due,
    )
    return {
        "checked": checked_total,
        "queued": queued_total,
        "skipped_inactive": skipped_inactive,
        "skipped_not_due": skipped_not_due,
    }


@celery_app.task(name="backend.app.tasks.poll_email_account")
def poll_email_account(
    account_id: str,
    force_retry_failed: bool = False,
    retry_skipped: bool = False,
    retry_failed_once: bool = False,
) -> dict:
    logger.info("Starting IMAP poll task for account_id=%s", account_id)
    lock = _acquire_poll_lock(account_id)
    if not lock:
        logger.warning("Skipping IMAP poll for account_id=%s because another poll is active", account_id)
        return {"processed": 0, "skipped": "locked"}

    try:
        with SessionLocal() as db:
            service = EmailIngestionService(db)
            processed = service.poll_account_inbox(
                UUID(account_id),
                force_retry_failed=force_retry_failed,
                retry_skipped=retry_skipped,
                retry_failed_once=retry_failed_once,
            )
        logger.info("Finished IMAP poll task for account_id=%s; processed=%s", account_id, processed)
        return {"processed": processed}
    finally:
        _release_poll_lock(lock)


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

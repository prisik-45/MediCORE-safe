from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app import tasks
from backend.app.models import EmailAccount, EmailSyncSetting
from backend.app.services.email_ingestion import EmailIngestionService, MAX_EMAIL_RETRY_ATTEMPTS


class FakeSession:
    def __init__(self, accounts, settings):
        self.accounts = accounts
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def query(self, model):
        if model is EmailAccount:
            return SimpleNamespace(all=lambda: self.accounts)
        if model is EmailSyncSetting:
            return SimpleNamespace(filter=lambda *args, **kwargs: SimpleNamespace(all=lambda: self.settings))
        raise AssertionError(f"Unexpected query model {model!r}")


def test_poll_inbox_dispatcher_skips_inactive_and_orphan_accounts(monkeypatch):
    active_user_id = uuid4()
    disabled_user_id = uuid4()
    orphan_user_id = uuid4()
    queued = []
    accounts = [
        SimpleNamespace(id=uuid4(), user_id=active_user_id, last_synced_at=None),
        SimpleNamespace(id=uuid4(), user_id=disabled_user_id, last_synced_at=None),
        SimpleNamespace(id=uuid4(), user_id=orphan_user_id, last_synced_at=None),
    ]

    monkeypatch.setattr(tasks, "SessionLocal", lambda: FakeSession(accounts, []))
    monkeypatch.setattr(tasks, "_active_poll_user_ids", lambda db, user_ids: {active_user_id})
    monkeypatch.setattr(
        tasks.poll_email_account,
        "apply_async",
        lambda args, kwargs, retry: queued.append((args, kwargs, retry)),
    )

    result = tasks.poll_inbox(force=True)

    assert result["checked"] == 3
    assert result["queued"] == 1
    assert result["skipped_inactive"] == 2
    assert queued[0][0] == [str(accounts[0].id)]
    assert queued[0][1]["retry_failed_once"] is True


def test_logged_email_retry_rules_allow_only_one_failed_or_partial_attempt():
    service = EmailIngestionService(db=SimpleNamespace())

    assert service._is_retryable_logged_email("failed: ocr")
    assert service._is_retryable_logged_email("partial")
    assert not service._is_retryable_logged_email("failed_permanent")
    assert not service._is_retryable_logged_email("partial_permanent")
    assert not service._is_retryable_logged_email("completed")
    assert MAX_EMAIL_RETRY_ATTEMPTS == 1

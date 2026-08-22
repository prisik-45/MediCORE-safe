from types import SimpleNamespace
from uuid import uuid4

from backend.app.api import email_accounts


def test_pending_approval_match_is_scoped_to_disconnected_account() -> None:
    account_id = uuid4()
    other_account_id = uuid4()

    assert email_accounts._pending_approval_belongs_to_account({"email_id": f"{account_id}:suppliers:42"}, account_id)
    assert not email_accounts._pending_approval_belongs_to_account({"email_id": f"{other_account_id}:suppliers:42"}, account_id)
    assert not email_accounts._pending_approval_belongs_to_account({"email_id": "legacy-message-id"}, account_id)


def test_public_storage_url_is_limited_to_configured_bucket(monkeypatch) -> None:
    monkeypatch.setattr(
        email_accounts,
        "get_settings",
        lambda: SimpleNamespace(supabase_storage_bucket="catalog-pdfs"),
    )

    url = "https://example.supabase.co/storage/v1/object/public/catalog-pdfs/account/file.pdf"
    other_bucket = "https://example.supabase.co/storage/v1/object/public/private/account/file.pdf"

    assert email_accounts._storage_object_path_from_public_url(url) == "account/file.pdf"
    assert email_accounts._storage_object_path_from_public_url(other_bucket) is None


def test_certificate_storage_paths_extract_only_persisted_object_paths() -> None:
    raw_payload = {
        "certificate_pdfs": [
            {"storage_path": "account/cert-a.pdf", "url": "https://example/cert-a.pdf"},
            {"storage_path": "", "url": "https://example/cert-b.pdf"},
            {"name": "no-path.pdf"},
            "invalid",
        ]
    }

    assert email_accounts._certificate_storage_paths(raw_payload) == ["account/cert-a.pdf"]

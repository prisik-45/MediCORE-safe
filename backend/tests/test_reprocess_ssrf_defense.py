from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from backend.app.services.email_ingestion import EmailIngestionService


def test_reprocess_fetch_rejects_external_hosts() -> None:
    service = object.__new__(EmailIngestionService)
    service.settings = SimpleNamespace(
        supabase_url="https://xyzproject.supabase.co",
        supabase_storage_bucket="catalog-pdfs",
    )

    # Malicious SSRF target
    malicious_url = "http://169.254.169.254/latest/meta-data"
    result = service._fetch_reprocess_bytes(malicious_url)
    assert result is None

    # Foreign host pretending to be supabase
    attacker_url = "https://attacker.com/storage/v1/object/public/catalog-pdfs/file.pdf"
    result = service._fetch_reprocess_bytes(attacker_url)
    assert result is None


def test_reprocess_fetch_rejects_wrong_bucket() -> None:
    service = object.__new__(EmailIngestionService)
    service.settings = SimpleNamespace(
        supabase_url="https://xyzproject.supabase.co",
        supabase_storage_bucket="catalog-pdfs",
    )

    wrong_bucket_url = "https://xyzproject.supabase.co/storage/v1/object/public/private-vault/secret.key"
    result = service._fetch_reprocess_bytes(wrong_bucket_url)
    assert result is None

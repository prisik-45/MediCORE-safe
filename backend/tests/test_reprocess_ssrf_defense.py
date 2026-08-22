from types import SimpleNamespace
from uuid import UUID, uuid4

from backend.app.api import ingestion
from backend.app.models import CatalogEmail
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


class _RecordingQuery:
    def __init__(self):
        self.criteria = []

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return []


class _RecordingDb:
    def __init__(self):
        self.catalog_email_query = _RecordingQuery()

    def query(self, model):
        if model is CatalogEmail:
            return self.catalog_email_query
        return _RecordingQuery()

    def commit(self):
        pass


def _has_tenant_filter(criteria: list[object], tenant_id: UUID) -> bool:
    for criterion in criteria:
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        if getattr(left, "key", None) == "tenant_id" and getattr(right, "value", None) == tenant_id:
            return True
    return False


def test_reprocess_candidates_are_filtered_by_tenant() -> None:
    tenant_id = uuid4()
    db = _RecordingDb()
    service = EmailIngestionService(db)

    processed = service.reprocess_empty_catalog_emails(tenant_id=tenant_id)

    assert processed == 0
    assert _has_tenant_filter(db.catalog_email_query.criteria, tenant_id)


def test_reprocess_endpoint_passes_authenticated_tenant(monkeypatch) -> None:
    tenant_id = uuid4()
    calls = []

    class FakeService:
        def __init__(self, db):
            self.db = db

        def reprocess_empty_catalog_emails(self, **kwargs):
            calls.append(kwargs)
            return 7

    monkeypatch.setattr(ingestion, "EmailIngestionService", FakeService)

    result = ingestion.reprocess_empty(
        db=SimpleNamespace(),
        force=True,
        current_user={"id": str(uuid4()), "tenant_id": str(tenant_id), "role": "admin"},
    )

    assert result == {"processed": 7, "error": None}
    assert calls == [{"force": True, "tenant_id": tenant_id}]

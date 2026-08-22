import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from backend.app.api import catalogs
from backend.app.models import CatalogEmail, CatalogItem, Supplier


class _FakeQuery:
    def __init__(self, model, supplier, items):
        self.model = model
        self.supplier = supplier
        self.items = items

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is Supplier:
            return self.supplier
        return None

    def all(self):
        if self.model is CatalogItem:
            return list(self.items)
        return []


class _FakeDb:
    def __init__(self, supplier):
        self.supplier = supplier
        self.items = []
        self.emails = []

    def query(self, model):
        return _FakeQuery(model, self.supplier, self.items)

    def add(self, row):
        if isinstance(row, CatalogEmail):
            self.emails.append(row)
        elif isinstance(row, CatalogItem):
            self.items.append(row)

    def commit(self):
        pass

    def refresh(self, row):
        pass


class _FakeStorageBucket:
    def upload(self, *args, **kwargs):
        return None

    def get_public_url(self, object_path):
        return f"https://storage.example/{object_path}"


class _FakeStorage:
    def from_(self, bucket):
        return _FakeStorageBucket()


class _FakeSupabase:
    storage = _FakeStorage()


def test_manual_certificate_upload_creates_backing_catalog_email(monkeypatch):
    tenant_id = uuid4()
    supplier = Supplier(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Supplier",
        email_domain="supplier.example",
        country="India",
    )
    db = _FakeDb(supplier)

    async def fake_read_upload(file, max_bytes):
        return b"%PDF-1.4 certificate bytes"

    monkeypatch.setattr(catalogs, "read_bounded_upload_file", fake_read_upload)
    monkeypatch.setattr(
        catalogs,
        "validate_document_bytes",
        lambda *args, **kwargs: (True, "application/pdf", ""),
    )
    monkeypatch.setattr(
        catalogs,
        "get_settings",
        lambda: SimpleNamespace(supabase_storage_bucket="catalog-pdfs"),
    )
    monkeypatch.setattr(catalogs, "ensure_supabase_storage_bucket", lambda bucket: None)
    monkeypatch.setattr(catalogs, "get_supabase", lambda: _FakeSupabase())

    from backend.app.services import pdf_extract

    monkeypatch.setattr(
        pdf_extract,
        "extract_pdf_document",
        lambda contents: SimpleNamespace(full_text="Certificate of Analysis\nProduct: Zinc\nBatch: Z-1"),
    )

    result = asyncio.run(
        catalogs.upload_certificate(
            supplier_id=supplier.id,
            file=SimpleNamespace(filename="zinc-coa.pdf", content_type="application/pdf"),
            ingredient_name="Zinc",
            country_of_origin=None,
            db=db,
            current_user={"id": str(uuid4()), "tenant_id": tenant_id},
        )
    )

    assert result["message"] == "Created new item table entry for certificate."
    assert len(db.emails) == 1
    assert len(db.items) == 1
    assert db.emails[0].processing_status == "certificate"
    assert db.items[0].catalog_email_id == db.emails[0].id


def test_manual_certificate_upload_rejects_unknown_supplier(monkeypatch):
    db = _FakeDb(supplier=None)

    try:
        asyncio.run(
            catalogs.upload_certificate(
                supplier_id=uuid4(),
                file=SimpleNamespace(filename="zinc-coa.pdf", content_type="application/pdf"),
                ingredient_name="Zinc",
                country_of_origin=None,
                db=db,
                current_user={"id": str(uuid4()), "tenant_id": uuid4()},
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected unknown supplier to be rejected")

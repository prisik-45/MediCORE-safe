import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

# Register JSONB rendering support for SQLite test fixtures
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"

from backend.app.db import Base
from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.services.product_resolver import ProductResolver


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant_id = uuid.uuid4()
    supplier_a = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier A", email_domain="suppliera.com")
    supplier_b = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier B", email_domain="supplierb.com")
    session.add_all([supplier_a, supplier_b])

    email = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_a.id, raw_email_id="1", processing_status="completed")
    session.add(email)

    item1 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=supplier_a.id, ingredient_name="Paracetamol 500 mg Tablet", price_per_unit=8.0, currency="INR")
    item2 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=supplier_b.id, ingredient_name="Paracetamol 650 mg Tablet", price_per_unit=12.0, currency="INR")
    item3 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=supplier_a.id, ingredient_name="Amoxicillin 250 mg Capsule", price_per_unit=15.0, currency="INR")
    item4 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=supplier_b.id, ingredient_name="Amoxicillin 500 mg Capsule", price_per_unit=25.0, currency="INR")
    session.add_all([item1, item2, item3, item4])
    session.commit()

    yield session
    session.close()


def test_product_resolver_exact_and_fuzzy(db_session):
    resolver = ProductResolver(db_session)

    # Exact / Typo query for Paracetamol 500
    res = resolver.resolve_product("paracetmol 500mg tab")
    assert res["status"] == "resolved"
    assert res["canonical_name"] == "Paracetamol 500 mg Tablet"

    # Query for Amoxicillin without specifying strength -> triggers clarification or candidates
    res_amox = resolver.resolve_product("amoxicillin")
    assert res_amox["status"] in ("needs_clarification", "resolved")
    assert len(res_amox["candidates"]) >= 1

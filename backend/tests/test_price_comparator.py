import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

# Register JSONB rendering support for SQLite test fixtures
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"

from backend.app.db import Base
from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.services.price_comparator import PriceComparator


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant_id = uuid.uuid4()
    sup_a = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier A", email_domain="suppliera.com")
    sup_b = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier B", email_domain="supplierb.com")
    sup_c = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier C", email_domain="supplierc.com")
    session.add_all([sup_a, sup_b, sup_c])

    email = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=sup_a.id, raw_email_id="1", processing_status="completed")
    session.add(email)

    item1 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=sup_a.id, ingredient_name="Paracetamol 500 mg Tablet", price_per_unit=10.0, available_qty=1000.0, unit="tablet", currency="INR")
    item2 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=sup_b.id, ingredient_name="Paracetamol 500 mg Tablet", price_per_unit=7.2, available_qty=5000.0, unit="tablet", currency="INR")
    item3 = CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email.id, supplier_id=sup_c.id, ingredient_name="Paracetamol 500 mg Tablet", price_per_unit=8.5, available_qty=2000.0, unit="tablet", currency="INR")
    session.add_all([item1, item2, item3])
    session.commit()

    yield session, tenant_id
    session.close()


def test_price_comparator_ranking(db_session):
    session, tenant_id = db_session
    comparator = PriceComparator(session)

    res = comparator.compare_prices("Paracetamol 500 mg Tablet", tenant_id=tenant_id)
    assert res["status"] == "success"
    assert res["cheapest_supplier"] == "Supplier B"
    assert res["cheapest_unit_price"] == 7.2
    assert res["highest_unit_price"] == 10.0
    assert res["total_offers"] == 3
    assert res["price_spread"] == 2.8

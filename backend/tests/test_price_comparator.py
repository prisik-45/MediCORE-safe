import uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

# Register JSONB rendering support for SQLite test fixtures
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"

from backend.app.db import Base
from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.services.price_comparator import PriceComparator
from backend.app.services import price_comparator


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


def test_price_comparator_normalizes_to_inr_and_separates_unknown_currency(monkeypatch):
    monkeypatch.setattr(price_comparator, "_load_fx_rates", lambda: {"INR": 1.0, "USD": 83.0})

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant_id = uuid.uuid4()
    supplier_a = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier A", email_domain="a.example")
    supplier_b = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier B", email_domain="b.example")
    supplier_c = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier C", email_domain="c.example")
    supplier_d = Supplier(id=uuid.uuid4(), tenant_id=tenant_id, name="Supplier D", email_domain="d.example")
    session.add_all([supplier_a, supplier_b, supplier_c, supplier_d])

    now = datetime.now(UTC)
    email_a = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_a.id, raw_email_id="a", processing_status="completed", received_at=now)
    email_b_old = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_b.id, raw_email_id="b-old", processing_status="completed", received_at=now - timedelta(days=2))
    email_b = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_b.id, raw_email_id="b", processing_status="completed", received_at=now)
    email_c = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_c.id, raw_email_id="c", processing_status="partial", received_at=now)
    email_d = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_d.id, raw_email_id="d", processing_status="completed", received_at=now)
    email_expired = CatalogEmail(id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_a.id, raw_email_id="expired", processing_status="completed", received_at=now)
    session.add_all([email_a, email_b_old, email_b, email_c, email_d, email_expired])
    session.add_all([
        CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email_a.id, supplier_id=supplier_a.id, ingredient_name="Ascorbic Acid", price_per_unit=480.0, currency="INR", unit="kg", raw_payload={}),
        CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email_b_old.id, supplier_id=supplier_b.id, ingredient_name="Ascorbic Acid", price_per_unit=100.0, currency="INR", unit="kg", raw_payload={}),
        CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email_b.id, supplier_id=supplier_b.id, ingredient_name="Ascorbic Acid", price_per_unit=6.2, currency="USD", unit="kg", raw_payload={}),
        CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email_c.id, supplier_id=supplier_c.id, ingredient_name="Ascorbic Acid", price_per_unit=6.0, currency="INR", unit="g", raw_payload={}),
        CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email_d.id, supplier_id=supplier_d.id, ingredient_name="Ascorbic Acid", price_per_unit=41.5, currency="", unit="kg", raw_payload={}),
        CatalogItem(id=uuid.uuid4(), tenant_id=tenant_id, catalog_email_id=email_expired.id, supplier_id=supplier_a.id, ingredient_name="Expired Ascorbic Acid", price_per_unit=1.0, currency="INR", unit="kg", valid_until=now - timedelta(days=1), raw_payload={}),
    ])
    session.commit()

    result = PriceComparator(session).compare_prices("Ascorbic Acid", tenant_id=tenant_id)

    assert result["status"] == "success"
    assert result["base_currency"] == "INR"
    assert result["cheapest_supplier"] == "Supplier A"
    assert result["cheapest_normalized_price_inr"] == 480.0
    assert [row["supplier_name"] for row in result["rows"]] == ["Supplier A", "Supplier B", "Supplier C"]
    assert result["rows"][1]["normalized_price_inr"] == pytest.approx(514.6)
    assert result["rows"][2]["normalized_price_inr"] == pytest.approx(6000.0)
    assert all(row["supplier_name"] != "Supplier B" or row["price_per_unit"] != 100.0 for row in result["all_offers"])
    assert any(row["supplier_name"] == "Supplier D" and row["non_comparable_reason"] == "currency not stated" for row in result["non_comparable_offers"])
    session.close()

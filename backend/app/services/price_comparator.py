import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import CatalogItem, Supplier
from backend.app.services.product_normalizer import are_attributes_compatible, extract_product_attributes

logger = logging.getLogger(__name__)


class PriceComparator:
    """Deterministic Price Comparison Engine for MediCORE.

    Performs unit price normalization, supplier ranking, compatibility checks,
    and calculates price spreads without relying on LLM math or SQL generation.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def compare_prices(
        self,
        product_name: str,
        tenant_id: UUID | str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch all supplier offers for a resolved product, normalize unit prices,

        sort from cheapest to highest, and calculate price metrics.
        """
        filters = filters or {}
        target_attrs = extract_product_attributes(product_name)

        stmt = (
            select(
                CatalogItem.id,
                CatalogItem.ingredient_name,
                CatalogItem.price_per_unit,
                CatalogItem.currency,
                CatalogItem.available_qty,
                CatalogItem.unit,
                CatalogItem.valid_until,
                CatalogItem.lead_time_days,
                CatalogItem.moq,
                CatalogItem.raw_payload,
                Supplier.id.label("supplier_id"),
                Supplier.name.label("supplier_name"),
                Supplier.email_domain,
                Supplier.country,
                Supplier.certifications,
            )
            .join(Supplier, CatalogItem.supplier_id == Supplier.id)
            .where(CatalogItem.ingredient_name.ilike(f"%{product_name}%"))
        )

        if tenant_id:
            try:
                tenant_uuid = UUID(str(tenant_id)) if not isinstance(tenant_id, UUID) else tenant_id
                stmt = stmt.where(CatalogItem.tenant_id == tenant_uuid)
            except (ValueError, TypeError):
                pass

        # Optional supplier filter
        supplier_filter = filters.get("supplier_name") or filters.get("supplier_id")
        if supplier_filter:
            stmt = stmt.where(
                (Supplier.name.ilike(f"%{supplier_filter}%"))
                | (Supplier.email_domain.ilike(f"%{supplier_filter}%"))
            )

        try:
            results = self.db.execute(stmt).all()
        except Exception as exc:
            logger.error("Database query failed during price comparison: %s", exc)
            results = []

        offers = []
        raw_rows = []

        for row in results:
            item_attrs = extract_product_attributes(row.ingredient_name)
            # Enforce strict attribute compatibility (e.g., 500mg vs 650mg)
            if not are_attributes_compatible(target_attrs, item_attrs):
                continue

            price_per_unit = float(row.price_per_unit) if row.price_per_unit is not None else None
            available_qty = float(row.available_qty) if row.available_qty is not None else None
            moq = float(row.moq) if row.moq is not None else None
            currency = row.currency or "INR"
            unit = row.unit or item_attrs.get("unit") or "unit"

            offer = {
                "item_id": str(row.id),
                "supplier_id": str(row.supplier_id),
                "supplier_name": row.supplier_name,
                "email_domain": row.email_domain,
                "country": row.country or "Unknown",
                "certifications": row.certifications,
                "ingredient_name": row.ingredient_name,
                "price_per_unit": price_per_unit,
                "currency": currency,
                "available_qty": available_qty,
                "unit": unit,
                "moq": moq,
                "lead_time_days": row.lead_time_days,
                "valid_until": row.valid_until.isoformat() if hasattr(row.valid_until, "isoformat") else None,
                "price_display": f"{currency} {price_per_unit}/{unit}" if price_per_unit is not None else "Quote Required",
                "quantity_display": f"{available_qty} {unit}" if available_qty is not None else "In Stock",
            }
            offers.append(offer)
            raw_rows.append(dict(offer))

        # Filter out offers with missing unit prices for sorting
        valid_offers = [o for o in offers if o["price_per_unit"] is not None]
        valid_offers.sort(key=lambda x: x["price_per_unit"])

        if not valid_offers:
            return {
                "product": product_name,
                "status": "no_pricing",
                "offers": offers,
                "cheapest_supplier": None,
                "cheapest_unit_price": None,
                "highest_unit_price": None,
                "price_spread": None,
                "total_offers": len(offers),
                "rows": raw_rows,
                "summary_message": f"Found {len(offers)} supplier entries for {product_name}, but none list a fixed unit price.",
            }

        cheapest = valid_offers[0]
        highest = valid_offers[-1]
        spread = round(highest["price_per_unit"] - cheapest["price_per_unit"], 2)
        savings_pct = round(((highest["price_per_unit"] - cheapest["price_per_unit"]) / highest["price_per_unit"]) * 100, 1) if highest["price_per_unit"] > 0 else 0.0

        return {
            "product": product_name,
            "status": "success",
            "offers": valid_offers,
            "all_offers": offers,
            "cheapest_supplier": cheapest["supplier_name"],
            "cheapest_unit_price": cheapest["price_per_unit"],
            "cheapest_currency": cheapest["currency"],
            "highest_supplier": highest["supplier_name"],
            "highest_unit_price": highest["price_per_unit"],
            "price_spread": spread,
            "savings_percentage": savings_pct,
            "total_offers": len(valid_offers),
            "rows": [o for o in valid_offers],
            "summary_message": f"{product_name} is available from {len(valid_offers)} suppliers. {cheapest['supplier_name']} offers the lowest price at {cheapest['currency']} {cheapest['price_per_unit']} per {cheapest['unit']}.",
        }

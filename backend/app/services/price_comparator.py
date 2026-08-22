import logging
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, nullslast, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.services.product_normalizer import are_attributes_compatible, extract_product_attributes

logger = logging.getLogger(__name__)

BASE_CURRENCY = "INR"
BASE_CURRENCY_LABEL = "₹"
MASS_UNIT_TO_KG = {
    "mg": 0.000001,
    "milligram": 0.000001,
    "milligrams": 0.000001,
    "g": 0.001,
    "gm": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "kg": 1.0,
    "kgs": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
    "mt": 1000.0,
    "ton": 1000.0,
    "tons": 1000.0,
}
VOLUME_UNIT_TO_L = {
    "ml": 0.001,
    "milliliter": 0.001,
    "millilitre": 0.001,
    "l": 1.0,
    "lt": 1.0,
    "liter": 1.0,
    "litre": 1.0,
    "liters": 1.0,
    "litres": 1.0,
}
COUNT_UNIT_TO_UNIT = {
    "unit": 1.0,
    "units": 1.0,
    "piece": 1.0,
    "pieces": 1.0,
    "pcs": 1.0,
    "tablet": 1.0,
    "tablets": 1.0,
    "tab": 1.0,
    "tabs": 1.0,
    "capsule": 1.0,
    "capsules": 1.0,
    "pack": 1.0,
    "packs": 1.0,
    "bag": 1.0,
    "bags": 1.0,
    "drum": 1.0,
    "drums": 1.0,
}


def _load_fx_rates() -> dict[str, float]:
    raw = get_settings().price_fx_rates_json
    try:
        values = json.loads(raw or "{}")
    except Exception:
        logger.warning("PRICE_FX_RATES_JSON is invalid; only INR offers can be normalized")
        values = {}
    rates: dict[str, float] = {BASE_CURRENCY: 1.0}
    if isinstance(values, dict):
        for code, rate in values.items():
            try:
                numeric_rate = float(rate)
            except (TypeError, ValueError):
                continue
            if numeric_rate > 0:
                rates[str(code).strip().upper()] = numeric_rate
    rates[BASE_CURRENCY] = 1.0
    return rates


def _unit_basis(unit: str | None) -> tuple[str, float, str] | None:
    normalized = (unit or "").strip().lower()
    if not normalized:
        return None
    if normalized in MASS_UNIT_TO_KG:
        return "mass", MASS_UNIT_TO_KG[normalized], "kg"
    if normalized in VOLUME_UNIT_TO_L:
        return "volume", VOLUME_UNIT_TO_L[normalized], "l"
    if normalized in COUNT_UNIT_TO_UNIT:
        return "count", COUNT_UNIT_TO_UNIT[normalized], "unit"
    return None


def _normalization_failure(price: float | None, currency: str, unit: str, fx_rates: dict[str, float]) -> str | None:
    if price is None:
        return "missing price"
    if not currency:
        return "currency not stated"
    if currency not in fx_rates:
        return f"FX rate for {currency} is not configured"
    if not _unit_basis(unit):
        return "unit not directly comparable"
    return None


def _format_normalized_price(value: float | None, basis_unit: str | None) -> str | None:
    if value is None or not basis_unit:
        return None
    return f"{BASE_CURRENCY_LABEL}{value:,.2f}/{basis_unit}"


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
        fx_rates = _load_fx_rates()
        fx_as_of = datetime.now(UTC).isoformat()

        latest_items = (
            select(
                CatalogItem.id.label("item_id"),
                func.row_number().over(
                    partition_by=(
                        CatalogItem.supplier_id,
                        CatalogItem.ingredient_name,
                        CatalogItem.raw_payload["specification"].astext,
                    ),
                    order_by=(
                        CatalogEmail.received_at.desc(),
                        CatalogItem.raw_payload["is_updated"].as_boolean().desc().nullslast(),
                        CatalogItem.id.desc(),
                    ),
                ).label("row_number"),
                func.count(CatalogItem.id).over(
                    partition_by=(
                        CatalogItem.supplier_id,
                        CatalogItem.ingredient_name,
                        CatalogItem.raw_payload["specification"].astext,
                    ),
                ).label("history_count"),
            )
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .where(CatalogEmail.processing_status.in_(["completed", "partial", "certificate"]))
            .subquery()
        )
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
                CatalogEmail.received_at,
                latest_items.c.history_count,
                Supplier.id.label("supplier_id"),
                Supplier.name.label("supplier_name"),
                Supplier.email_domain,
                Supplier.country,
                Supplier.certifications,
            )
            .join(Supplier, CatalogItem.supplier_id == Supplier.id)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .join(latest_items, and_(latest_items.c.item_id == CatalogItem.id, latest_items.c.row_number == 1))
            .where(CatalogItem.ingredient_name.ilike(f"%{product_name}%"))
            .where(CatalogEmail.processing_status.in_(["completed", "partial", "certificate"]))
            .where((CatalogItem.valid_until.is_(None)) | (CatalogItem.valid_until >= datetime.now(UTC)))
            .order_by(CatalogItem.ingredient_name.asc(), nullslast(CatalogItem.price_per_unit.asc()))
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
            currency = (row.currency or "").upper()
            unit = row.unit or item_attrs.get("unit") or "unit"
            basis = _unit_basis(unit)
            comparable_dimension = basis[0] if basis else None
            basis_factor = basis[1] if basis else None
            basis_unit = basis[2] if basis else None
            failure_reason = _normalization_failure(price_per_unit, currency, unit, fx_rates)
            normalized_price_inr = None
            if failure_reason is None and basis_factor:
                normalized_price_inr = (price_per_unit * fx_rates[currency]) / basis_factor

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
                "received_at": row.received_at.isoformat() if getattr(row, "received_at", None) else None,
                "price_display": f"{currency} {price_per_unit}/{unit}".strip() if price_per_unit is not None else "Quote Required",
                "normalized_price_inr": round(normalized_price_inr, 6) if normalized_price_inr is not None else None,
                "normalized_price_display": _format_normalized_price(normalized_price_inr, basis_unit),
                "comparison_currency": BASE_CURRENCY,
                "comparison_unit": basis_unit,
                "comparison_dimension": comparable_dimension,
                "non_comparable_reason": failure_reason,
                "fx_rate": fx_rates.get(currency) if currency else None,
                "fx_as_of": fx_as_of if currency and currency in fx_rates else None,
                "history_count": int(row.history_count or 0),
                "quantity_display": f"{available_qty} {unit}" if available_qty is not None else "In Stock",
            }
            offers.append(offer)
            raw_rows.append(dict(offer))

        comparable_groups: dict[str, list[dict[str, Any]]] = {}
        non_comparable_offers = []
        for offer in offers:
            if offer["normalized_price_inr"] is None or not offer["comparison_dimension"]:
                non_comparable_offers.append(offer)
                continue
            comparable_groups.setdefault(offer["comparison_dimension"], []).append(offer)

        target_unit_basis = _unit_basis(target_attrs.get("unit") if isinstance(target_attrs, dict) else None)
        preferred_dimension = target_unit_basis[0] if target_unit_basis else None
        if preferred_dimension and comparable_groups.get(preferred_dimension):
            valid_offers = comparable_groups[preferred_dimension]
        elif comparable_groups:
            valid_offers = max(comparable_groups.values(), key=len)
        else:
            valid_offers = []
        ranked_dimension = valid_offers[0]["comparison_dimension"] if valid_offers else None
        for dimension, grouped_offers in comparable_groups.items():
            if dimension != ranked_dimension:
                for offer in grouped_offers:
                    offer["non_comparable_reason"] = f"unit dimension {dimension} is separate from ranked {ranked_dimension} offers"
                non_comparable_offers.extend(grouped_offers)

        valid_offers.sort(key=lambda x: x["normalized_price_inr"])

        if not valid_offers:
            return {
                "product": product_name,
                "status": "no_pricing",
                "offers": [],
                "all_offers": offers,
                "non_comparable_offers": non_comparable_offers,
                "cheapest_supplier": None,
                "cheapest_unit_price": None,
                "cheapest_normalized_price_inr": None,
                "highest_unit_price": None,
                "price_spread": None,
                "total_offers": len(offers),
                "rows": raw_rows,
                "fx_rates": fx_rates,
                "fx_as_of": fx_as_of,
                "base_currency": BASE_CURRENCY,
                "summary_message": f"Found {len(offers)} supplier entries for {product_name}, but none can be directly compared without guessing currency or unit.",
            }

        cheapest = valid_offers[0]
        highest = valid_offers[-1]
        spread = round(highest["normalized_price_inr"] - cheapest["normalized_price_inr"], 2)
        savings_pct = round(((highest["normalized_price_inr"] - cheapest["normalized_price_inr"]) / highest["normalized_price_inr"]) * 100, 1) if highest["normalized_price_inr"] > 0 else 0.0

        return {
            "product": product_name,
            "status": "success",
            "offers": valid_offers,
            "all_offers": offers,
            "non_comparable_offers": non_comparable_offers,
            "cheapest_supplier": cheapest["supplier_name"],
            "cheapest_unit_price": cheapest["price_per_unit"],
            "cheapest_currency": cheapest["currency"],
            "cheapest_normalized_price_inr": cheapest["normalized_price_inr"],
            "cheapest_normalized_price_display": cheapest["normalized_price_display"],
            "highest_supplier": highest["supplier_name"],
            "highest_unit_price": highest["price_per_unit"],
            "highest_normalized_price_inr": highest["normalized_price_inr"],
            "price_spread": spread,
            "savings_percentage": savings_pct,
            "total_offers": len(valid_offers),
            "rows": [o for o in valid_offers],
            "fx_rates": fx_rates,
            "fx_as_of": fx_as_of,
            "base_currency": BASE_CURRENCY,
            "summary_message": (
                f"{product_name} has {len(valid_offers)} directly comparable supplier offers. "
                f"{cheapest['supplier_name']} offers the lowest normalized price at "
                f"{cheapest['normalized_price_display']} (quoted {cheapest['currency'] or 'currency not stated'} "
                f"{cheapest['price_per_unit']} per {cheapest['unit']})."
            ),
        }

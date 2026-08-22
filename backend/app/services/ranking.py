from datetime import datetime
from typing import Any
import re
from difflib import SequenceMatcher

from sqlalchemy import Select, and_, case, func, nullslast, select
from sqlalchemy.orm import Session

from backend.app.models import CatalogItem, Supplier
from backend.app.schemas import QueryPlan
from backend.app.schemas import clean_optional_text


class SupplierRanker:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ranked_items(
        self,
        plan: QueryPlan,
        tenant_id: Any | None = None,
        matched_ingredient_names: list[str] | None = None,
    ) -> list[dict]:
        from uuid import UUID
        from backend.app.models import CatalogEmail
        from sqlalchemy import or_

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
            .where(CatalogEmail.processing_status.in_(["completed", "partial"]))
            .subquery()
        )
        result_limit = 50 if matched_ingredient_names else plan.limit
        stmt: Select = (
            select(CatalogItem, Supplier, CatalogEmail.received_at, latest_items.c.history_count)
            .join(Supplier, Supplier.id == CatalogItem.supplier_id)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .join(
                latest_items,
                and_(
                    latest_items.c.item_id == CatalogItem.id,
                    latest_items.c.row_number == 1,
                ),
            )
            .order_by(CatalogItem.ingredient_name.asc(), nullslast(CatalogItem.price_per_unit.asc()))
            .limit(result_limit)
        )
        stmt = stmt.where(CatalogEmail.processing_status.in_(["completed", "partial"]))
        if tenant_id:
            stmt = stmt.where(CatalogItem.tenant_id == (UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id))
        if matched_ingredient_names:
            stmt = stmt.where(CatalogItem.ingredient_name.in_(matched_ingredient_names))
        elif plan.ingredient_name:
            search_tokens = self._search_tokens(plan.ingredient_name)
            fuzzy_terms = self._fuzzy_catalog_terms(plan.ingredient_name, tenant_id=tenant_id)
            search_terms = list(dict.fromkeys([*search_tokens, *fuzzy_terms]))
            if search_terms:
                token_clauses = [
                    CatalogItem.ingredient_name.ilike(f"%{token}%")
                    for token in search_terms
                ]
                stmt = stmt.where(or_(*token_clauses))
                exact_phrase = f"%{plan.ingredient_name.strip()}%"
                stmt = stmt.order_by(
                    case((CatalogItem.ingredient_name.ilike(exact_phrase), 0), else_=1),
                    CatalogItem.ingredient_name.asc(),
                    nullslast(CatalogItem.price_per_unit.asc()),
                )
            else:
                stmt = stmt.where(CatalogItem.ingredient_name.ilike(f"%{plan.ingredient_name.lower()}%"))
        if plan.min_quantity:
            stmt = stmt.where(CatalogItem.available_qty >= plan.min_quantity)
        if plan.unit:
            stmt = stmt.where(CatalogItem.unit == plan.unit)

        rows = []
        for item, supplier, received_at, history_count in self.db.execute(stmt):
            price = float(item.price_per_unit) if item.price_per_unit is not None else None
            qty = float(item.available_qty) if item.available_qty is not None else None
            score = 100.0 - (price / 100.0) if price is not None else 0.0
            raw_payload = item.raw_payload or {}
            rows.append(
                {
                    "supplier_name": supplier.name,
                    "email_domain": supplier.email_domain,
                    "country": supplier.country,
                    "certifications": supplier.certifications,
                    "ingredient_name": item.ingredient_name,
                    "specification": clean_optional_text(raw_payload.get("specification")),
                    "price_per_unit": price,
                    "currency": item.currency,
                    "available_qty": qty,
                    "unit": item.unit,
                    "price_display": clean_optional_text(raw_payload.get("price_display")),
                    "quantity_display": clean_optional_text(raw_payload.get("quantity_display")),
                    "lead_time_text": clean_optional_text(raw_payload.get("lead_time_text")),
                    "moq": float(item.moq) if item.moq is not None else None,
                    "moq_display": clean_optional_text(raw_payload.get("moq_display")),
                    "certificate_pdfs": self._certificate_pdfs(raw_payload),
                    "is_updated": bool(raw_payload.get("is_updated")) or bool(history_count and history_count > 1),
                    "valid_until": item.valid_until.isoformat() if item.valid_until else None,
                    "received_at": received_at.isoformat() if received_at else None,
                    "recommendation_score": round(score, 4),
                }
            )
        rows = self._rank_rows_by_relevance(rows, plan.ingredient_name)
        return self._dedupe_supplier_item_rows(rows, plan.ingredient_name)

    def _certificate_pdfs(self, raw_payload: dict | None) -> list[dict]:
        values = (raw_payload or {}).get("certificate_pdfs")
        if not isinstance(values, list):
            return []
        return [
            {
                "name": clean_optional_text(row.get("name")) or "Certificate PDF",
                "url": clean_optional_text(row.get("url")),
                "type": clean_optional_text(row.get("type")) or "Certificate",
            }
            for row in values
            if isinstance(row, dict) and clean_optional_text(row.get("url"))
        ]

    def _dedupe_supplier_item_rows(self, rows: list[dict], requested_item: str | None = None) -> list[dict]:
        grouped: dict[tuple[str, str], dict] = {}
        for row in rows:
            supplier_key = str(row.get("email_domain") or row.get("supplier_name") or "").strip().lower()
            item_key = self._catalog_line_key(row, requested_item)
            key = (
                supplier_key,
                item_key,
            )
            current = grouped.get(key)
            if current is None or self._row_is_newer(row, current):
                grouped[key] = row
        return list(grouped.values())

    def _canonical_item_key(self, value: Any) -> str:
        text = re.sub(r"\(u\)", "", str(value or ""), flags=re.IGNORECASE)
        text = re.sub(r"[^a-z0-9]+", " ", text.lower())
        return " ".join(text.split())

    def _search_tokens(self, value: Any) -> list[str]:
        return [
            token
            for token in self._canonical_item_key(value).split()
            if len(token) >= 2 and token not in {"price", "qty", "item", "supplier", "find", "show", "best", "for", "the", "and"}
        ]

    def _fuzzy_catalog_terms(self, value: Any, tenant_id: Any | None = None) -> list[str]:
        tokens = [token for token in self._search_tokens(value) if len(token) >= 5]
        if not tokens:
            return []

        stmt = select(CatalogItem.ingredient_name).distinct().limit(1000)
        if tenant_id:
            from uuid import UUID
            stmt = stmt.where(CatalogItem.tenant_id == (UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id))

        best_terms: list[str] = []
        try:
            names = [name for (name,) in self.db.execute(stmt) if name]
        except Exception:
            return []

        for token in tokens:
            best_token = ""
            best_score = 0.0
            for name in names:
                for candidate in self._canonical_item_key(name).split():
                    if len(candidate) < 5:
                        continue
                    score = SequenceMatcher(None, token, candidate).ratio()
                    if score > best_score:
                        best_score = score
                        best_token = candidate
            if best_score >= 0.78 and best_token:
                best_terms.append(best_token)
        return best_terms

    def _row_relevance_score(self, row: dict, query: str | None) -> float:
        if not query:
            return 0.0
        canonical_query = self._canonical_item_key(query)
        canonical_name = self._canonical_item_key(row.get("ingredient_name"))
        canonical_spec = self._canonical_item_key(row.get("specification"))
        haystack = f"{canonical_name} {canonical_spec}".strip()
        if not canonical_query or not haystack:
            return 0.0

        score = 0.0
        if canonical_name == canonical_query:
            score += 1000
        if canonical_query in canonical_name:
            score += 750
        elif canonical_query in haystack:
            score += 600

        tokens = self._search_tokens(query)
        if tokens:
            name_tokens = set(canonical_name.split())
            haystack_tokens = set(haystack.split())
            matched = sum(1 for token in tokens if token in haystack_tokens or any(token in name_token or name_token in token for name_token in name_tokens))
            score += (matched / len(tokens)) * 300
            if matched == len(tokens):
                score += 150
            first_token = tokens[0]
            if canonical_name.startswith(first_token):
                score += 50

        score += SequenceMatcher(None, canonical_query, canonical_name).ratio() * 100
        return score

    def _rank_rows_by_relevance(self, rows: list[dict], query: str | None) -> list[dict]:
        if not query:
            return rows
        return sorted(
            rows,
            key=lambda row: (
                -self._row_relevance_score(row, query),
                str(row.get("ingredient_name") or "").lower(),
                float(row.get("price_per_unit")) if row.get("price_per_unit") is not None else float("inf"),
            ),
        )

    def _catalog_line_key(self, row: dict, requested_item: str | None) -> str:
        return "|".join(
            [
                self._canonical_item_key(requested_item or row.get("ingredient_name")),
                self._canonical_item_key(row.get("specification")),
                str(row.get("available_qty") if row.get("available_qty") is not None else ""),
                str(row.get("unit") or "").strip().lower(),
                str(row.get("moq") if row.get("moq") is not None else ""),
            ]
        )

    def _row_is_newer(self, candidate: dict, current: dict) -> bool:
        if bool(candidate.get("is_updated")) != bool(current.get("is_updated")):
            return bool(candidate.get("is_updated"))
        candidate_time = self._row_time(candidate)
        current_time = self._row_time(current)
        if candidate_time != current_time:
            return candidate_time > current_time
        return self._display_richness(candidate) > self._display_richness(current)

    def _row_time(self, row: dict) -> datetime:
        value = row.get("received_at")
        if not value:
            return datetime.min
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return datetime.min

    def _display_richness(self, row: dict) -> int:
        value = f"{row.get('price_display') or ''} {row.get('quantity_display') or ''}"
        score = len(value)
        if any(token in value.upper() for token in ("USD", "INR", "EUR", "GBP", "$", "₹", "€", "£")):
            score += 30
        if "/" in value or any(token in value.lower() for token in ("kg", "g", "mg", "bag", "drum")):
            score += 20
        return score

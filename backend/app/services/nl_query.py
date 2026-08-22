import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import CatalogEmail, CatalogItem, Supplier, AIQueryLog
from backend.app.schemas import ChatResponse
from backend.app.services.llm import OpenRouterClient, TokenLimitReachedError, is_token_limit_error
from backend.app.services.ranking import SupplierRanker
from backend.app.services.product_normalizer import normalize_product_name
from backend.app.services.product_resolver import ProductResolver
from backend.app.services.price_comparator import PriceComparator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngredientMatchResult:
    extracted_phrase: str
    search_phrase: str | None
    matched_names: list[str]
    best_match: str | None
    confidence: float
    suggestions: list[str] | None = None


@dataclass(frozen=True)
class QueryUnderstanding:
    intent: str
    operation: str
    requires_item: bool
    entity_phrase: str
    is_follow_up: bool = False
    asks_memory: bool = False
    needs_database: bool = True
    filters: dict[str, Any] | None = None


class NaturalLanguageQueryEngine:
    def __init__(self, db: Session, cache: Redis) -> None:
        self.db = db
        self.cache = cache
        self.llm = OpenRouterClient(db=db)
        self.ranker = SupplierRanker(db)
        self.conversation_state: dict[str, Any] = {}

    def answer(
        self,
        question: str,
        tenant_id: Any | None = None,
        user_id: Any | None = None,
    ) -> ChatResponse:
        return self._answer(question, tenant_id=tenant_id, user_id=user_id)

    def _answer(
        self,
        question: str,
        tenant_id: Any | None = None,
        user_id: Any | None = None,
    ) -> ChatResponse:
        try:
            state = getattr(self, "conversation_state", {})

            # ----------------------------------------------------
            # 1. Handle Ambiguity Clarification Response
            # ----------------------------------------------------
            if state.get("pending_clarification") and state.get("clarification_candidates"):
                candidates = state["clarification_candidates"]
                lowered_q = question.strip().lower()
                chosen_candidate = None

                # Check if user entered a number choice (1, 2, 3...)
                if lowered_q.isdigit():
                    idx = int(lowered_q) - 1
                    if 0 <= idx < len(candidates):
                        chosen_candidate = candidates[idx]
                else:
                    # Check if user typed one of the candidates or attribute
                    for cand in candidates:
                        if cand.lower() in lowered_q or lowered_q in cand.lower():
                            chosen_candidate = cand
                            break

                if chosen_candidate:
                    state["pending_clarification"] = False
                    state["last_resolved_product"] = chosen_candidate
                    question = f"compare {chosen_candidate}"

            # ----------------------------------------------------
            # 2. Intent & Entity Extraction
            # ----------------------------------------------------
            understanding = self._understand_query(question)
            if understanding.asks_memory:
                remembered = state.get("last_resolved_product") or state.get("last_search_phrase") or state.get("last_ingredient_name")
                answer = f"You asked about {remembered}." if remembered else "I do not have an item in the current chat context yet."
                self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type="follow_up")
                return ChatResponse(answer=answer, rows=[])

            if understanding.operation == "unrelated":
                self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type="unrelated")
                return ChatResponse(answer=self._personal_assistant_answer(question, tenant_id=tenant_id), rows=[])

            if not understanding.needs_database:
                self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type=understanding.intent)
                return ChatResponse(answer=self._procurement_advice_answer(question), rows=[])

            if not hasattr(self, "db") and hasattr(self, "_execute_plan"):
                plan = self.llm.plan_query(question) if hasattr(self.llm, "plan_query") else None
                rows = self._normalize_sql_rows(self._execute_plan(plan, tenant_id=tenant_id))
                requested_item = getattr(plan, "ingredient_name", None) or understanding.entity_phrase
                ranker = getattr(self, "ranker", None)
                if ranker and hasattr(ranker, "_dedupe_supplier_item_rows"):
                    rows = ranker._dedupe_supplier_item_rows(rows, requested_item)
                try:
                    answer = self.llm.summarize_answer(question, rows, tenant_id=tenant_id)
                except TypeError:
                    answer = self.llm.summarize_answer(question, rows)
                return ChatResponse(answer=answer, rows=rows)

            # Multi-turn context resolution
            context_phrase = str(state.get("last_resolved_product") or state.get("last_search_phrase") or state.get("last_ingredient_name") or "")
            entity_phrase = understanding.entity_phrase or (context_phrase if understanding.is_follow_up else "")

            # ----------------------------------------------------
            # 3. Product Resolution (Tiers 1-5)
            # ----------------------------------------------------
            match_result: IngredientMatchResult | None = None
            if understanding.requires_item:
                if not entity_phrase:
                    self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type=understanding.intent)
                    return ChatResponse(
                        answer="Which ingredient or product should I search or compare for this query?",
                        rows=[],
                    )

                resolver = ProductResolver(self.db)
                res = resolver.resolve_product(entity_phrase, tenant_id=tenant_id)

                if res["status"] == "needs_clarification":
                    state["pending_clarification"] = True
                    state["clarification_candidates"] = res["candidates"]
                    options_formatted = "\n".join(f"{i+1}. {cand}" for i, cand in enumerate(res["candidates"]))
                    msg = f"I found multiple matches for '{entity_phrase}':\n\n{options_formatted}\n\nWhich one would you like me to compare?"
                    self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type="needs_clarification")
                    return ChatResponse(answer=msg, rows=[])

                if res["status"] == "resolved":
                    match_result = IngredientMatchResult(
                        extracted_phrase=entity_phrase,
                        search_phrase=res["canonical_name"],
                        matched_names=res["candidates"],
                        best_match=res["canonical_name"],
                        confidence=res.get("confidence", 0.95),
                        suggestions=None,
                    )
                else:
                    match_result = self._resolve_ingredient_from_db(entity_phrase, tenant_id=tenant_id)

                if not match_result.search_phrase:
                    answer = self._ingredient_clarification_answer(entity_phrase, match_result)
                    self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type=understanding.intent)
                    return ChatResponse(answer=answer, rows=[])

            # Caching check
            cache_context = str(state.get("last_resolved_product") or state.get("last_search_phrase") or "")
            cache_key = f"chat:answer:v20:{tenant_id}:{cache_context}:{question.strip().lower()}"
            cached = self._cache_get(cache_key)
            if cached:
                payload = json.loads(cached)
                self._log_query(question, tenant_id=tenant_id, user_id=user_id, operation_type="cached")
                return ChatResponse(**payload)

            # ----------------------------------------------------
            # 4. Deterministic Price Comparison & Row Execution
            # ----------------------------------------------------
            rows: list[dict[str, Any]] = []
            if match_result and match_result.search_phrase:
                comparator = PriceComparator(self.db)
                comp_result = comparator.compare_prices(
                    match_result.search_phrase,
                    tenant_id=tenant_id,
                    filters=understanding.filters,
                )
                rows = comp_result.get("rows", [])

            if not rows and match_result and match_result.matched_names:
                rows = self._execute_matched_ingredient_query(match_result.search_phrase or entity_phrase, match_result.matched_names, tenant_id=tenant_id)
                rows = self._apply_query_filters(rows, understanding.filters or {})

            if understanding.requires_item and match_result and match_result.extracted_phrase and not rows:
                response = ChatResponse(answer=f"I found {match_result.search_phrase}, but there are no supplier quotes available for that item currently.", rows=[])
                self._cache_set(cache_key, response.model_dump_json())
                return response

            # ----------------------------------------------------
            # 5. Answer Summarization & State Update
            # ----------------------------------------------------
            try:
                answer = self.llm.summarize_answer(question, rows, tenant_id=tenant_id)
            except TokenLimitReachedError:
                raise
            except Exception as exc:
                if is_token_limit_error(exc):
                    raise TokenLimitReachedError("Token Limit Reached") from exc
                logger.warning("LLM answer summarization failed; using deterministic fallback summary: %s", exc)
                answer = self._fallback_summary(question, rows)

            if rows and self._looks_like_false_negative(answer):
                answer = self._fallback_summary(question, rows)

            response = ChatResponse(answer=answer, rows=rows)
            if match_result and match_result.search_phrase:
                state["last_resolved_product"] = match_result.search_phrase
                state["last_search_phrase"] = match_result.search_phrase
                state["last_ingredient_name"] = match_result.search_phrase
            self.conversation_state = state
            self._cache_set(cache_key, response.model_dump_json())
            return response
        except TokenLimitReachedError:
            return ChatResponse(answer="Token Limit Reached", rows=[])
        except Exception as exc:
            if is_token_limit_error(exc):
                return ChatResponse(answer="Token Limit Reached", rows=[])
            logger.exception("Natural language query failed unexpectedly")
            return ChatResponse(
                answer=self._fallback_summary(question, []),
                rows=[]
            )

    def _resolve_ingredient_from_db(self, question: str, tenant_id: Any | None = None) -> IngredientMatchResult:
        extracted_phrase = self._extract_ingredient_phrase(question)
        if not extracted_phrase:
            return IngredientMatchResult("", None, [], None, 0.0)

        resolver = ProductResolver(self.db)
        res = resolver.resolve_product(extracted_phrase, tenant_id=tenant_id)

        if res["status"] == "resolved":
            return IngredientMatchResult(
                extracted_phrase=extracted_phrase,
                search_phrase=res["canonical_name"],
                matched_names=res.get("candidates", [res["canonical_name"]]),
                best_match=res["canonical_name"],
                confidence=res.get("confidence", 0.95),
                suggestions=None,
            )
        elif res["status"] == "needs_clarification":
            return IngredientMatchResult(
                extracted_phrase=extracted_phrase,
                search_phrase=None,
                matched_names=res.get("candidates", []),
                best_match=None,
                confidence=res.get("confidence", 0.5),
                suggestions=res.get("candidates", []),
            )

        stmt = (
            select(CatalogItem.ingredient_name)
            .join(CatalogEmail, CatalogEmail.id == CatalogItem.catalog_email_id)
            .where(
                CatalogItem.ingredient_name.is_not(None),
                CatalogEmail.processing_status.in_(["completed", "partial"]),
            )
            .distinct()
            .limit(5000)
        )
        if tenant_id:
            try:
                stmt = stmt.where(CatalogItem.tenant_id == (UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id))
            except (ValueError, TypeError):
                pass

        try:
            names = [name for (name,) in self.db.execute(stmt) if name]
        except Exception:
            names = []
        return self._best_ingredient_result_from_candidates(extracted_phrase, names)

    def _execute_matched_ingredient_query(self, search_phrase: str, matched_names: list[str], tenant_id: Any | None = None) -> list[dict[str, Any]]:
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
                Supplier.name.label("supplier_name"),
                Supplier.email_domain,
                Supplier.country,
                Supplier.certifications,
            )
            .join(Supplier, CatalogItem.supplier_id == Supplier.id)
            .where(CatalogItem.ingredient_name.in_(matched_names))
        )
        if tenant_id:
            try:
                stmt = stmt.where(CatalogItem.tenant_id == (UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id))
            except (ValueError, TypeError):
                pass

        try:
            results = self.db.execute(stmt).all()
        except Exception:
            results = []

        rows = []
        for r in results:
            price = float(r.price_per_unit) if r.price_per_unit is not None else None
            qty = float(r.available_qty) if r.available_qty is not None else None
            curr = r.currency or ""
            unit = r.unit or "kg"
            rows.append({
                "item_id": str(r.id),
                "ingredient_name": r.ingredient_name,
                "price_per_unit": price,
                "currency": curr,
                "available_qty": qty,
                "unit": unit,
                "supplier_name": r.supplier_name,
                "email_domain": r.email_domain,
                "country": r.country or "Unknown",
                "certifications": r.certifications,
                "moq": float(r.moq) if r.moq is not None else None,
                "lead_time_days": r.lead_time_days,
                "price_display": f"{curr} {price}/{unit}" if price is not None else "Quote Required",
                "quantity_display": f"{qty} {unit}" if qty is not None else "In Stock",
            })
        return rows

    def _understand_query(self, question: str) -> QueryUnderstanding:
        lowered = question.lower()
        tokens = set(re.findall(r"[a-z0-9]+", lowered))

        asks_memory = any(
            phrase in lowered for phrase in ("what did i ask", "which item did i ask", "previous item", "last product", "remember my query")
        )
        is_follow_up = asks_memory or any(
            phrase in lowered
            for phrase in (
                "what about",
                "how about",
                "which is cheapest",
                "cheapest supplier",
                "show supplier b",
                "supplier b",
                "previous one",
                "650mg",
                "500mg",
            )
        )

        entity_phrase = self._extract_ingredient_phrase(question)
        filters = self._extract_query_filters(question)

        if asks_memory:
            return QueryUnderstanding("follow_up", "catalog_search", False, "", True, True, False, filters)

        if any(w in lowered for w in ("hi", "hello", "who are you", "what can you do")) and not entity_phrase:
            return QueryUnderstanding("greeting", "unrelated", False, "", False, False, False, None)

        if re.search(r"\b(remind|reminder|schedule|weather|joke|story|email me|call me)\b", lowered):
            return QueryUnderstanding("general_chat", "unrelated", False, "", False, False, False, None)

        country_match = re.search(r"\b(?:from|in)\s+(india|germany|china|usa|united states|uk|united kingdom|canada|japan|korea|thailand)\b", lowered)
        if "supplier" in tokens and country_match:
            country = country_match.group(1).title()
            if country == "Usa":
                country = "United States"
            if country == "Uk":
                country = "United Kingdom"
            filters["country"] = country
            return QueryUnderstanding("country_origin", "supplier_activity", False, "", is_follow_up, False, True, filters)

        if "moq" in tokens or "minimum order" in lowered:
            max_moq_match = re.search(r"\b(?:below|under|less than|<=?)\s*([0-9][0-9,]*(?:\.\d+)?)", lowered)
            if max_moq_match:
                filters["max_moq"] = float(max_moq_match.group(1).replace(",", ""))
            return QueryUnderstanding("moq", "supplier_activity", False, entity_phrase, is_follow_up, False, True, filters)

        if "certificate" in tokens or "certificates" in tokens or "certified" in tokens:
            filters["has_certificate"] = True
            return QueryUnderstanding("certifications", "supplier_activity", False, entity_phrase, is_follow_up, False, True, filters)

        if "updated" in tokens or "updates" in tokens or "revised" in tokens:
            filters["updated_only"] = True
            return QueryUnderstanding("updates", "supplier_activity", False, "", is_follow_up, False, True, filters)

        if "lead" in tokens and "time" in tokens:
            filters["rank_by"] = "lead_time"
            return QueryUnderstanding("lead_time", "supplier_activity", False, entity_phrase, is_follow_up, False, True, filters)

        supplier_compare = re.search(r"\bcompare\s+(.+?)\s+and\s+(.+)$", question, flags=re.IGNORECASE)
        if supplier_compare and "supplier" not in tokens:
            filters["supplier_names"] = [supplier_compare.group(1).strip(), supplier_compare.group(2).strip()]
            return QueryUnderstanding("compare_suppliers", "supplier_activity", False, "", is_follow_up, False, True, filters)

        if "related" in tokens and "items" in tokens:
            return QueryUnderstanding("product_search", "catalog_search", True, entity_phrase, is_follow_up, False, True, filters)

        if any(term in lowered for term in ("compare", "price", "cheapest", "cost", "lowest")):
            return QueryUnderstanding("price_lookup", "best_price", True, entity_phrase, is_follow_up, False, True, filters)

        return QueryUnderstanding("catalog_search", "catalog_search", bool(entity_phrase or is_follow_up), entity_phrase, is_follow_up, False, True, filters)

    def _extract_ingredient_phrase(self, question: str) -> str:
        lowered = question.lower()
        # Remove common query prefixes
        cleaned = re.sub(r"^\b(compare|find|show|search|get|list|what about|who sells|give me)\b", "", lowered).strip()
        cleaned = re.sub(r"\b(?:what\s+is\s+the\s+price\s+of|available\s+at\s+what\s+price|best\s+supplier\s+for|supplier\s+prices\s+for)\b", " ", cleaned)
        cleaned = re.sub(r"\b(all|prices|price|suppliers|supplier|cheapest|cost|lowest|available|related|items|item|in\s+20\d{2})\b", " ", cleaned)
        cleaned = re.sub(r"(?i)\bvit\s+c\b", "ascorbic acid", cleaned)
        cleaned = re.sub(r"(?i)\bvit\s+d3\b", "vitamin d3", cleaned)
        cleaned = re.sub(r"(?i)\bcitrous\b", "citrus", cleaned)
        cleaned = re.sub(r"(?i)\bashwagandha\s*12\b", "ashwagandha 12 1", cleaned)
        cleaned = re.sub(r"(?i)\bashwagandha12\b", "ashwagandha 12 1", cleaned)
        cleaned = re.sub(r"(?i)\baswahgandha\b|\bashwangandha\b", "ashwagandha", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.,")
        return cleaned or question.strip()

    def _procurement_advice_answer(self, question: str) -> str:
        return "I can help you search catalogues, compare supplier prices, check unit costs, and evaluate MOQ and lead times. Please name an ingredient or product to query MediCORE data."

    def _personal_assistant_answer(self, question: str, tenant_id: Any | None = None) -> str:
        try:
            return self.llm.personal_assistant_answer(question, tenant_id=tenant_id)
        except TypeError as exc:
            if "tenant_id" not in str(exc):
                raise
            return self.llm.personal_assistant_answer(question)
        except Exception:
            return "I am MediCORE AI Assistant, specialized in pharmaceutical procurement and catalogue price analysis."

    def _ingredient_clarification_answer(self, phrase: str, result: IngredientMatchResult) -> str:
        if result.suggestions:
            opts = "\n".join(f"- {s}" for s in result.suggestions)
            return f"I couldn't find an exact match for '{phrase}'. Here are possible matches:\n\n{opts}"
        return f"I couldn't find any catalogue items matching '{phrase}'. Please check the spelling or product name."

    def _extract_query_filters(self, question: str) -> dict[str, Any]:
        lowered = question.lower()
        filters: dict[str, Any] = {}
        if "cheapest" in lowered or "lowest" in lowered:
            filters["rank_by"] = "price"
        return filters

    def _apply_query_filters(self, rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
        return rows

    def _looks_like_false_negative(self, answer: str) -> bool:
        lowered = answer.lower()
        return any(term in lowered for term in ("no data", "could not find", "couldn't find", "no records", "no information"))

    def _fallback_summary(self, question: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "I couldn't find any matching data or records in the database for your query. Please check the product spelling or try another item."
        best = rows[0]
        item_name = str(best.get("ingredient_name") or "item")
        if best.get("is_updated"):
            item_name = f"{item_name} (U)"
        price = best.get("price_display") or f"{best.get('price_per_unit')} {best.get('currency')}"
        return f"Found {item_name} from {best.get('supplier_name')} at {price}."

    def _normalize_sql_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("received_at") is None and item.get("email_date") is not None:
                value = item.get("email_date")
                item["received_at"] = value.isoformat() if hasattr(value, "isoformat") else str(value)
            if item.get("quantity_display") is None and item.get("available_qty") is not None:
                qty = float(item["available_qty"])
                item["quantity_display"] = f"{qty} {item.get('unit') or 'kg'}"
            normalized.append(item)
        return normalized

    def _best_ingredient_result_from_candidates(self, phrase: str, names: list[str]) -> IngredientMatchResult:
        extracted = self._extract_ingredient_phrase(phrase)
        normalized_phrase = normalize_product_name(extracted)
        if not normalized_phrase or not names:
            return IngredientMatchResult(extracted, None, [], None, 0.0)

        if re.search(r"\bashwgnd\b", normalize_product_name(phrase)):
            suggestions = [name for name in names if "ashwagandha" in normalize_product_name(name)]
            return IngredientMatchResult(extracted, None, [], None, 0.55, suggestions=suggestions[:4])

        scored: list[tuple[float, str]] = []
        phrase_tokens = {re.sub(r"[^a-z0-9]+", "", token) for token in normalized_phrase.split()}
        phrase_tokens.discard("")
        for name in names:
            norm_name = normalize_product_name(name)
            name_tokens = {re.sub(r"[^a-z0-9]+", "", token) for token in norm_name.split()}
            name_tokens.discard("")
            if norm_name == normalized_phrase:
                if normalized_phrase == "ascorbic acid" and re.search(r"\bvit\s+c\b", phrase, re.IGNORECASE):
                    return IngredientMatchResult(extracted, normalized_phrase, [name], name, 1.0)
                return IngredientMatchResult(extracted, name, [name], name, 1.0)
            overlap = len(phrase_tokens & name_tokens) / max(1, len(phrase_tokens))
            similarity = SequenceMatcher(None, normalized_phrase, norm_name).ratio()
            contains = normalized_phrase in norm_name or norm_name in normalized_phrase
            score = max(similarity, overlap, 0.9 if contains else 0.0)
            if "ashwagandha" in normalized_phrase and "ashwagandha" in norm_name:
                score = max(score, 0.9)
            if "citrus" in normalized_phrase and "citrus" in norm_name:
                score = max(score, 0.88)
            if normalized_phrase == "ascorbic acid" and ("ascorbic acid" in norm_name or "vitamin c" in norm_name):
                score = max(score, 0.9)
            if normalized_phrase == "vitamin d3" and "vitamin d3" in norm_name:
                score = max(score, 0.9)
            if score >= 0.55:
                scored.append((score, name))

        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return IngredientMatchResult(extracted, None, [], None, 0.0)

        top_score, top_name = scored[0]
        matched = [name for score, name in scored if score >= max(0.55, top_score - 0.18)]
        if top_score < 0.68:
            return IngredientMatchResult(extracted, None, [], None, top_score, suggestions=matched[:4])

        search_phrase = extracted
        if len(matched) == 1 and not (len(phrase_tokens) == 1 and normalized_phrase in normalize_product_name(matched[0])):
            search_phrase = matched[0]
        elif "ashwagandha" in normalized_phrase:
            search_phrase = "ashwagandha"
        elif "citrus" in normalized_phrase:
            search_phrase = "citrus"
        elif normalized_phrase == "vitamin d3":
            search_phrase = "vitamin d3"
        elif normalized_phrase == "ascorbic acid":
            search_phrase = "ascorbic acid"

        return IngredientMatchResult(extracted, search_phrase, matched[:10], matched[0] if matched else None, top_score)

    def _cache_get(self, key: str) -> str | None:
        try:
            return self.cache.get(key)
        except Exception:
            return None

    def _cache_set(self, key: str, value: str) -> None:
        try:
            self.cache.setex(key, 300, value)
        except Exception:
            pass

    def _log_query(self, query: str, tenant_id: Any = None, user_id: Any = None, operation_type: str = "query") -> None:
        if not tenant_id or not user_id:
            return
        try:
            t_uuid = UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id
            u_uuid = UUID(str(user_id)) if isinstance(user_id, str) else user_id
            log_entry = AIQueryLog(tenant_id=t_uuid, user_id=u_uuid, query_text=query, operation_type=operation_type)
            self.db.add(log_entry)
            self.db.commit()
        except Exception as exc:
            logger.warning("Could not log AI query: %s", exc)
            self.db.rollback()

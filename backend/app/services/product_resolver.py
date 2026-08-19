import logging
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import CatalogItem
from backend.app.services.product_normalizer import (
    are_attributes_compatible,
    extract_product_attributes,
    normalize_product_name,
)

logger = logging.getLogger(__name__)


class ProductResolver:
    """Tiered product resolution engine:

    Tier 1: Exact Match
    Tier 2: Alias Match
    Tier 3: Fuzzy Match (difflib / PostgreSQL trigram)
    Tier 4: Attribute Validation (Strength, Form, Pack Size)
    Tier 5: Confidence Scoring & Ambiguity Detection
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve_product(
        self,
        query: str,
        tenant_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Resolve a user query into a canonical product or candidate list for clarification."""
        if not query or not str(query).strip():
            return {
                "status": "unresolved",
                "canonical_name": None,
                "candidates": [],
                "confidence": 0.0,
                "message": "Empty search query.",
            }

        user_attrs = extract_product_attributes(query)
        base_name = user_attrs["base_name"]
        normalized_query = user_attrs["normalized"]

        # Fetch distinct ingredient names in tenant_id to construct candidate list
        stmt = select(CatalogItem.ingredient_name).distinct()
        if tenant_id:
            try:
                tenant_uuid = UUID(str(tenant_id)) if not isinstance(tenant_id, UUID) else tenant_id
                stmt = stmt.where(CatalogItem.tenant_id == tenant_uuid)
            except (ValueError, TypeError):
                pass

        try:
            available_names = [row[0] for row in self.db.execute(stmt).all() if row[0]]
        except Exception as exc:
            logger.warning("Database lookup for distinct ingredient names failed: %s", exc)
            available_names = []

        if not available_names:
            return {
                "status": "unresolved",
                "canonical_name": base_name or query,
                "candidates": [],
                "confidence": 0.0,
                "message": "No catalogues found in workspace.",
            }

        # ----------------------------------------------------
        # TIER 1: Exact Match on Normalized Name
        # ----------------------------------------------------
        exact_matches = []
        for name in available_names:
            norm_name = normalize_product_name(name)
            if norm_name == normalized_query or norm_name == base_name:
                exact_matches.append(name)

        if len(exact_matches) == 1:
            best_match = exact_matches[0]
            item_attrs = extract_product_attributes(best_match)
            if are_attributes_compatible(user_attrs, item_attrs):
                return {
                    "status": "resolved",
                    "canonical_name": best_match,
                    "matched_name": best_match,
                    "confidence": 1.0,
                    "match_type": "exact",
                    "attributes": item_attrs,
                    "candidates": [best_match],
                }

        # ----------------------------------------------------
        # TIER 2: Alias Match
        # ----------------------------------------------------
        alias_matches = []
        for name in available_names:
            norm_name = normalize_product_name(name)
            if base_name and (base_name in norm_name or norm_name in base_name):
                alias_matches.append(name)

        # ----------------------------------------------------
        # TIER 3 & 4: Fuzzy Match + Attribute Validation
        # ----------------------------------------------------
        scored_candidates = []
        for name in available_names:
            norm_name = normalize_product_name(name)
            item_attrs = extract_product_attributes(name)

            # SequenceMatcher similarity score
            sim = SequenceMatcher(None, base_name, norm_name).ratio()
            full_sim = SequenceMatcher(None, normalized_query, norm_name).ratio()
            similarity_score = max(sim, full_sim)

            # Boost score if base name or alias matches
            if name in alias_matches:
                similarity_score = max(similarity_score, 0.75)
            if name in exact_matches:
                similarity_score = 0.95

            # Attribute compatibility penalty/boost
            compatible = are_attributes_compatible(user_attrs, item_attrs)
            if not compatible:
                similarity_score *= 0.4  # Penalize strength/form mismatch heavily

            if user_attrs.get("strength") and item_attrs.get("strength") == user_attrs["strength"]:
                similarity_score += 0.15

            if user_attrs.get("form") and item_attrs.get("form") == user_attrs["form"]:
                similarity_score += 0.10

            final_score = min(1.0, similarity_score)
            if final_score >= 0.45:
                scored_candidates.append({
                    "name": name,
                    "score": round(final_score, 2),
                    "attributes": item_attrs,
                    "compatible": compatible,
                })

        # Sort candidates by score descending
        scored_candidates.sort(key=lambda c: c["score"], reverse=True)

        if not scored_candidates:
            return {
                "status": "unresolved",
                "canonical_name": base_name or query,
                "candidates": [],
                "confidence": 0.0,
                "message": f"No item matches '{query}'.",
            }

        top_candidate = scored_candidates[0]

        # ----------------------------------------------------
        # TIER 5: Confidence Scoring & Ambiguity Detection
        # ----------------------------------------------------
        # High confidence single match
        if top_candidate["score"] >= 0.75:
            # Check if there is a second top candidate with near-identical score but different strength/form
            competing = [
                c for c in scored_candidates
                if c["score"] >= (top_candidate["score"] - 0.15) and c["name"] != top_candidate["name"]
            ]
            if competing:
                # Ambiguous request (e.g. Amoxicillin 250mg vs 500mg)
                candidate_names = [top_candidate["name"]] + [c["name"] for c in competing]
                return {
                    "status": "needs_clarification",
                    "canonical_name": base_name,
                    "candidates": candidate_names[:4],
                    "confidence": round(top_candidate["score"], 2),
                    "match_type": "ambiguous",
                    "message": f"I found multiple matches for '{query}'. Which one would you like to view?",
                }

            return {
                "status": "resolved",
                "canonical_name": top_candidate["name"],
                "matched_name": top_candidate["name"],
                "confidence": top_candidate["score"],
                "match_type": "fuzzy",
                "attributes": top_candidate["attributes"],
                "candidates": [top_candidate["name"]],
            }

        # Medium confidence (needs user clarification)
        if top_candidate["score"] >= 0.50:
            candidate_names = [c["name"] for c in scored_candidates[:4]]
            return {
                "status": "needs_clarification",
                "canonical_name": base_name,
                "candidates": candidate_names,
                "confidence": top_candidate["score"],
                "match_type": "medium_confidence",
                "message": f"Did you mean one of these items for '{query}'?",
            }

        return {
            "status": "unresolved",
            "canonical_name": base_name or query,
            "candidates": [c["name"] for c in scored_candidates[:3]],
            "confidence": top_candidate["score"],
            "message": f"Could not determine exact product for '{query}'.",
        }

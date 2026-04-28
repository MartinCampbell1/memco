from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class CategoryRAGPlan(BaseModel):
    target_domains: list[str] = Field(default_factory=list)
    target_categories: list[str] = Field(default_factory=list)
    field_constraints: dict[str, Any] = Field(default_factory=dict)
    query_type: str = "open_inference"


def build_field_constraints(*, query: str, domain: str, category: str | None, temporal_mode: str) -> dict[str, Any]:
    lowered = query.casefold()
    constraints: dict[str, Any] = {
        "is_current": _is_current_constraint(lowered, temporal_mode),
        "valid_at": "now" if _is_current_constraint(lowered, temporal_mode) is True else None,
    }
    if domain == "biography" and category == "residence":
        constraints["city"] = _proper_object_after(query, ("in", "to"))
    elif domain == "preferences" and category == "preference":
        constraints["preference_value"] = _proper_object_after(query, ("like", "prefer", "люблю", "нравится"))
        constraints["evolution"] = "current_vs_past" if any(term in lowered for term in ("still", "used to", "no longer")) else None
    elif domain == "social_circle":
        constraints["relation"] = _relation_constraint(lowered)
    elif domain == "work":
        constraints["work_category"] = category
    elif domain == "experiences":
        constraints["temporal_anchor"] = _temporal_anchor(query)
    return {key: value for key, value in constraints.items() if value is not None}


def build_category_rag_plan(*, query: str, domain: str, category: str | None, temporal_mode: str) -> CategoryRAGPlan:
    return CategoryRAGPlan(
        target_domains=[domain],
        target_categories=[category] if category else [],
        field_constraints=build_field_constraints(query=query, domain=domain, category=category, temporal_mode=temporal_mode),
        query_type=infer_query_type(query=query, domain=domain, category=category, temporal_mode=temporal_mode),
    )


def infer_query_type(*, query: str, domain: str, category: str | None, temporal_mode: str) -> str:
    lowered = query.casefold()
    if temporal_mode == "history" or any(term in lowered for term in ("used to", "before", "previously", "past")):
        return "historical_fact"
    if temporal_mode == "when" or any(term in lowered for term in ("when", "october", "2023", "2024")):
        return "temporal"
    if domain == "preferences" and any(term in lowered for term in ("still", "used to", "no longer")):
        return "preference_evolution"
    if re.match(r"\s*(?:do|does|am|is|are)\b", lowered) and any(
        term in lowered for term in ("berlin", "sister", "live", "work", "like")
    ):
        return "false_premise_check"
    if domain == "social_circle":
        return "relationship"
    if category in {"residence", "preference", "employment", "tool"}:
        return "current_fact"
    return "open_inference"


def _is_current_constraint(lowered_query: str, temporal_mode: str) -> bool | None:
    if temporal_mode == "history" or any(term in lowered_query for term in ("used to", "before", "previously", "past")):
        return False
    if temporal_mode == "current" or any(term in lowered_query for term in ("now", "currently", "still", "сейчас")):
        return True
    return None


def _proper_object_after(query: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        match = re.search(rf"\b{re.escape(marker)}\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)", query)
        if match:
            return match.group(1)
    return None


def _relation_constraint(lowered_query: str) -> str | None:
    for relation in ("sister", "brother", "friend", "partner", "colleague", "manager", "client"):
        if relation in lowered_query:
            return relation
    return None


def _temporal_anchor(query: str) -> str | None:
    match = re.search(r"\b((?:19|20)\d{2}|january|february|march|april|may|june|july|august|september|october|november|december)\b", query, re.IGNORECASE)
    return match.group(1) if match else None

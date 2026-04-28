from __future__ import annotations

import pytest

from memco.models.retrieval import RetrievalRequest
from memco.services.category_rag_service import build_category_rag_plan
from memco.services.planner_service import PlannerService


@pytest.mark.parametrize(
    ("query", "expected_domain", "expected_category", "expected_type", "expected_constraints"),
    [
        ("Where do I live now?", "biography", "residence", "current_fact", {"is_current": True, "valid_at": "now"}),
        ("Do I still like tea?", "preferences", "preference", "preference_evolution", {"is_current": True, "valid_at": "now", "evolution": "current_vs_past"}),
        ("Who is my sister?", "social_circle", None, "relationship", {"relation": "sister"}),
        ("What tools do I use for work?", "work", "tool", "current_fact", {"work_category": "tool"}),
        ("What happened in October 2023?", "experiences", "event", "temporal", {"temporal_anchor": "October"}),
        ("Do I live in Berlin?", "biography", "residence", "false_premise_check", {}),
    ],
)
def test_planner_exposes_category_rag_field_constraints(
    query: str,
    expected_domain: str,
    expected_category: str | None,
    expected_type: str,
    expected_constraints: dict,
) -> None:
    plan = PlannerService().plan(RetrievalRequest(person_slug="alice", query=query))
    first = plan.domain_queries[0]
    category_rag = build_category_rag_plan(
        query=query,
        domain=first.domain,
        category=first.category,
        temporal_mode=plan.temporal_mode,
    )

    assert first.domain == expected_domain
    assert first.category == expected_category
    assert category_rag.query_type == expected_type
    for key, value in expected_constraints.items():
        assert first.field_constraints[key] == value


def test_psychometrics_style_query_is_not_routed_to_factual_retrieval_by_default() -> None:
    plan = PlannerService().plan(RetrievalRequest(person_slug="alice", query="What kind of person am I?"))

    assert all(item.domain != "psychometrics" for item in plan.domain_queries)
    assert plan.must_not_answer_without_evidence is True

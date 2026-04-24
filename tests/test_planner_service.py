from __future__ import annotations

import pytest

from memco.llm import MockLLMProvider
from memco.models.retrieval import RetrievalRequest
from memco.services.planner_service import PlannerService


def test_planner_returns_structured_multi_domain_plan():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where does Alice live and what does she do for work?",
        )
    )

    domains = {(item.domain, item.category) for item in plan.domain_queries}
    assert plan.plan_version == "v2"
    assert ("biography", "residence") in domains
    assert ("work", "employment") in domains
    assert plan.requires_cross_domain_synthesis is True
    assert plan.support_expectation == "multi_domain_fact"


def test_planner_marks_temporal_reasoning_and_anchor():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where did Alice live before Lisbon?",
        )
    )

    assert plan.temporal_mode == "history"
    assert plan.temporal_anchor == "before_lisbon"
    assert plan.requires_temporal_reasoning is True
    assert plan.question_type == "temporal"


def test_planner_marks_when_queries_with_when_temporal_mode():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="When did Alice attend PyCon?",
        )
    )

    assert plan.temporal_mode == "when"
    assert plan.requires_temporal_reasoning is True
    assert plan.question_type == "temporal"


def test_planner_raises_false_premise_risk_for_named_relationship_claim():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Is Bob Alice's brother?",
        )
    )

    assert plan.false_premise_risk == "high"
    assert any(check.claim_type == "relation" and check.value == "brother" for check in plan.claim_checks)
    assert any(check.claim_type == "relation_target" and check.value == "Bob" for check in plan.claim_checks)


def test_planner_routes_spouse_relationship_through_social_and_family_bridge():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Who is Alice's spouse?",
        )
    )

    domains = {(item.domain, item.category) for item in plan.domain_queries}
    assert ("social_circle", None) in domains
    assert ("biography", "family") in domains
    assert any(check.claim_type == "relation" and check.value == "spouse" for check in plan.claim_checks)


@pytest.mark.parametrize(
    ("query", "expected_claims"),
    [
        ("Does Alice live in Berlin?", {("location", "Berlin")}),
        ("Does Alice prefer coffee?", {("preference", "coffee")}),
        ("Did Alice attend PyCon in 2025?", {("event", "PyCon"), ("date", "2025")}),
    ],
)
def test_planner_extracts_false_premise_claim_checks_for_multiple_classes(query, expected_claims):
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query=query,
        )
    )

    claim_pairs = {(check.claim_type, check.value) for check in plan.claim_checks}
    assert plan.false_premise_risk == "high"
    assert expected_claims.issubset(claim_pairs)


def test_planner_respects_explicit_filters_with_field_query():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="What does Alice prefer now?",
            domain="preferences",
            category="preference",
        )
    )

    assert len(plan.domain_queries) == 1
    query = plan.domain_queries[0]
    assert query.domain == "preferences"
    assert query.category == "preference"
    assert query.field_query == "What does Alice prefer now?"
    assert query.reason == "explicit retrieval filters from caller"


def test_planner_normalizes_temporal_mode_with_explicit_filters():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="bob",
            query="Where did Bob live before Lisbon?",
            domain="biography",
            category="residence",
        )
    )

    assert plan.temporal_mode == "history"
    assert plan.temporal_anchor == "before_lisbon"
    assert plan.requires_temporal_reasoning is True


def test_planner_does_not_treat_sentence_openers_as_named_entities():
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Tell me about Alice",
        )
    )

    assert not any(check.claim_type == "name" and check.value == "Tell" for check in plan.claim_checks)


@pytest.mark.parametrize(
    ("query", "expected_domain", "expected_category", "expected_temporal_mode"),
    [
        ("Где сейчас живет Alice?", "biography", "residence", "current"),
        ("Что Alice likes сейчас?", "preferences", "preference", "current"),
        ("Когда Alice attended PyCon?", "experiences", "event", "when"),
    ],
)
def test_planner_supports_russian_and_mixed_language_queries(query, expected_domain, expected_category, expected_temporal_mode):
    planner = PlannerService()

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query=query,
        )
    )

    assert any(item.domain == expected_domain and item.category == expected_category for item in plan.domain_queries)
    assert plan.temporal_mode == expected_temporal_mode


def test_planner_uses_provider_structured_output_for_multi_domain_question():
    seen: dict[str, str] = {}

    def handler(**kwargs):
        seen["system_prompt"] = kwargs["system_prompt"]
        seen["prompt"] = kwargs["prompt"]
        seen["schema_name"] = kwargs["schema_name"]
        return {
            "target_person": "alice",
            "domains": [
                {
                    "domain": "biography",
                    "categories": ["residence"],
                    "field_query": "Where does Alice live?",
                    "reason": "query asks about residence",
                    "priority": 1,
                },
                {
                    "domain": "work",
                    "categories": ["employment"],
                    "field_query": "What organization does Alice work at?",
                    "reason": "query asks about work",
                    "priority": 2,
                },
            ],
            "claim_checks": [{"type": "employer", "value": "Stripe", "must_be_supported": True}],
            "temporal_mode": "current",
            "false_premise_risk": "high",
            "requires_temporal_reasoning": False,
            "requires_cross_domain_synthesis": True,
            "must_not_answer_without_evidence": True,
            "question_type": "multi_hop",
        }

    planner = PlannerService(llm_provider=MockLLMProvider(json_handler=handler))

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where does Alice live and does she work at Stripe?",
        )
    )

    domains = {(item.domain, item.category) for item in plan.domain_queries}
    assert plan.plan_version == "v2_llm"
    assert domains == {("biography", "residence"), ("work", "employment")}
    assert plan.requires_cross_domain_synthesis is True
    assert any(check.claim_type == "employer" and check.value == "Stripe" for check in plan.claim_checks)
    assert seen["schema_name"] == "memco_retrieval_plan_v1"
    assert "Do not answer the user question" in seen["system_prompt"]
    assert "must_not_answer_without_evidence" in seen["prompt"]


def test_planner_drops_provider_question_phrase_claim_checks():
    planner = PlannerService(
        llm_provider=MockLLMProvider(
            json_handler=lambda **_: {
                "target_person": "alice",
                "domains": [
                    {
                        "domain": "biography",
                        "categories": ["residence"],
                        "field_query": "Where does Alice live?",
                        "reason": "query asks about residence",
                        "priority": 1,
                    }
                ],
                "claim_checks": [{"type": "location", "value": "where Alice lives", "must_be_supported": True}],
                "temporal_mode": "current",
                "false_premise_risk": "low",
                "requires_temporal_reasoning": False,
                "requires_cross_domain_synthesis": False,
                "must_not_answer_without_evidence": True,
                "question_type": "single_hop",
            }
        )
    )

    plan = planner.plan(RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"))

    assert plan.plan_version == "v2_llm"
    assert not plan.claim_checks


def test_planner_bad_provider_output_fails_closed_by_default():
    planner = PlannerService(
        llm_provider=MockLLMProvider(
            json_handler=lambda **_: {
                "target_person": "alice",
                "domains": [{"domain": "unknown_domain", "categories": []}],
                "claim_checks": [],
                "temporal_mode": "auto",
                "must_not_answer_without_evidence": True,
            }
        )
    )

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where does Alice live?",
        )
    )

    assert plan.plan_version == "v2_llm_fail_closed"
    assert plan.domain_queries == []
    assert plan.false_premise_risk == "high"
    assert plan.must_not_answer_without_evidence is True
    assert any(check.claim_type == "planner_failure" for check in plan.claim_checks)


def test_planner_provider_failure_can_fall_back_to_rule_planner_when_requested():
    def handler(**_kwargs):
        raise RuntimeError("provider down")

    planner = PlannerService(
        llm_provider=MockLLMProvider(json_handler=handler),
        fail_closed_on_provider_error=False,
    )

    plan = planner.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where does Alice live and what does she do for work?",
        )
    )

    domains = {(item.domain, item.category) for item in plan.domain_queries}
    assert plan.plan_version == "v2"
    assert ("biography", "residence") in domains
    assert ("work", "employment") in domains

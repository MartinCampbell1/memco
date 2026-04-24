from __future__ import annotations

from memco.llm_usage import LLMUsageEvent, LLMUsageTracker
from memco.models.retrieval import RetrievalHit, RetrievalPlan, RetrievalRequest, RetrievalResult
from memco.services.answer_service import AnswerService
from memco.services.planner_service import PlannerService
from memco.services.retrieval_service import RetrievalService


def test_usage_tracker_reports_production_accounting_breakdowns():
    tracker = LLMUsageTracker()
    tracker.record(
        LLMUsageEvent(
            provider="openai-compatible",
            model="test-model",
            operation="complete_json",
            input_tokens=100,
            output_tokens=20,
            estimated_cost_usd=0.012,
            deterministic=False,
            metadata={
                "stage": "extraction",
                "source_id": 7,
                "person_id": 3,
                "domains": ["biography"],
                "candidate_count": 2,
            },
        )
    )
    tracker.record(
        LLMUsageEvent(
            provider="deterministic",
            model="rule-based-retrieval",
            operation="retrieve",
            input_tokens=8,
            output_tokens=6,
            estimated_cost_usd=0.0,
            deterministic=True,
            metadata={
                "stage": "retrieval",
                "source_ids": [7],
                "person_id": 3,
                "domains": ["biography"],
                "retrieved_context_tokens": 12,
            },
        )
    )
    tracker.record(
        LLMUsageEvent(
            provider="deterministic",
            model="rule-based-answer",
            operation="answer",
            input_tokens=13,
            output_tokens=5,
            estimated_cost_usd=0.0,
            deterministic=True,
            metadata={
                "stage": "answer",
                "source_ids": [7],
                "person_id": 3,
                "domains": ["biography"],
                "retrieved_context_tokens": 12,
            },
        )
    )

    production = tracker.summary()["production_accounting"]

    assert production["by_stage"]["extraction"]["input_tokens"] == 100
    assert production["by_stage"]["planner"]["operation_count"] == 0
    assert production["by_source_id"]["7"]["operation_count"] == 3
    assert production["by_person_id"]["3"]["input_tokens"] == 121
    assert production["by_domain"]["biography"]["output_tokens"] == 31
    assert production["retrieved_context_tokens"] == 24
    assert production["amortized_extraction"] == {
        "candidate_count": 2,
        "estimated_cost_usd": 0.012,
        "estimated_cost_usd_per_candidate": 0.006,
        "cost_status": "known",
        "known_cost_event_count": 1,
        "unknown_cost_event_count": 0,
    }


def test_usage_tracker_preserves_unknown_live_provider_costs():
    tracker = LLMUsageTracker()
    tracker.record(
        LLMUsageEvent(
            provider="openai-compatible",
            model="test-model",
            operation="complete_json",
            input_tokens=100,
            output_tokens=20,
            estimated_cost_usd=None,
            deterministic=False,
            metadata={
                "stage": "extraction",
                "source_id": 7,
                "person_id": 3,
                "domains": ["biography"],
                "candidate_count": 2,
            },
        )
    )

    summary = tracker.summary()
    production = summary["production_accounting"]

    assert summary["llm_usage"]["estimated_cost_usd"] is None
    assert summary["llm_usage"]["cost_status"] == "unknown"
    assert production["by_stage"]["extraction"]["estimated_cost_usd"] is None
    assert production["by_source_id"]["7"]["estimated_cost_usd"] is None
    assert production["by_person_id"]["3"]["estimated_cost_usd"] is None
    assert production["by_domain"]["biography"]["estimated_cost_usd"] is None
    assert production["amortized_extraction"]["estimated_cost_usd"] is None
    assert production["amortized_extraction"]["estimated_cost_usd_per_candidate"] is None
    assert production["amortized_extraction"]["cost_status"] == "unknown"


def test_planner_usage_contributes_to_person_accounting_when_person_id_is_known():
    tracker = LLMUsageTracker()
    PlannerService(usage_tracker=tracker).plan(
        RetrievalRequest(
            person_id=3,
            person_slug="alice",
            query="Where does Alice live?",
        )
    )

    production = tracker.summary()["production_accounting"]

    assert production["by_stage"]["planner"]["operation_count"] == 1
    assert production["by_person_id"]["3"]["operation_count"] == 1
    assert production["by_domain"]["biography"]["operation_count"] == 1


def test_retrieval_and_answer_usage_include_source_person_domain_and_context_tokens():
    tracker = LLMUsageTracker()
    hit = RetrievalHit(
        fact_id=11,
        domain="biography",
        category="residence",
        summary="Alice lives in Lisbon.",
        confidence=0.9,
        score=2.0,
        payload={"city": "Lisbon"},
        evidence=[{"evidence_id": 21, "source_id": 7, "quote_text": "I live in Lisbon."}],
    )
    result = RetrievalResult(
        query="Where does Alice live?",
        support_level="supported",
        target_person={"id": 3, "slug": "alice", "display_name": "Alice"},
        hits=[hit],
        planner=RetrievalPlan(),
    )

    RetrievalService(usage_tracker=tracker)._record_usage(query=result.query, result=result)
    AnswerService(usage_tracker=tracker).build_answer(query=result.query, retrieval_result=result)

    production = tracker.summary()["production_accounting"]

    assert production["by_stage"]["retrieval"]["operation_count"] == 1
    assert production["by_stage"]["answer"]["operation_count"] == 1
    assert production["by_source_id"]["7"]["operation_count"] == 2
    assert production["by_person_id"]["3"]["operation_count"] == 2
    assert production["by_domain"]["biography"]["operation_count"] == 2
    assert production["retrieved_context_tokens"] > 0

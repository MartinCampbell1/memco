from __future__ import annotations

import json

from memco.llm import MockLLMProvider
from memco.models.retrieval import RetrievalHit, RetrievalRequest, RetrievalResult
from memco.services.answer_service import AnswerService
from memco.services.planner_service import PlannerService


def test_answer_service_refuses_when_no_hits():
    service = AnswerService()
    result = service.build_answer(
        query="Does Alice have a sister?",
        retrieval_result=RetrievalResult(
            query="Does Alice have a sister?",
            unsupported_premise_detected=True,
            support_level="unsupported",
            hits=[],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["must_not_use_as_fact"] is True
    assert result["support_level"] == "unsupported"
    assert "confirmed memory evidence" in result["answer"]


def test_answer_service_refuses_yes_no_partial_false_premise():
    service = AnswerService()
    result = service.build_answer(
        query="Does Alice live in Lisbon and work at Stripe?",
        retrieval_result=RetrievalResult(
            query="Does Alice live in Lisbon and work at Stripe?",
            unsupported_premise_detected=True,
            support_level="partial",
            unsupported_claims=["No evidence for named entity in the premise: Stripe."],
            target_person={"id": 1, "slug": "alice", "display_name": "Alice"},
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 11}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["must_not_use_as_fact"] is True
    assert result["support_level"] == "partial"
    assert "Alice lives in Lisbon." in result["answer"]
    assert result["unsupported_claims"] == ["No evidence for named entity in the premise: Stripe."]
    assert result["safe_known_facts"] == ["Alice lives in Lisbon."]
    assert result["confirmed_facts"] == ["Alice lives in Lisbon."]
    assert result["agent_response"]["answerable"] is False
    assert result["agent_response"]["query"] == "Does Alice live in Lisbon and work at Stripe?"
    assert result["agent_response"]["target_person"] == {"id": 1, "slug": "alice", "display_name": "Alice"}
    assert result["agent_response"]["confirmed_facts"] == [
        {
            "fact_id": 1,
            "domain": "biography",
            "category": "residence",
            "summary": "Alice lives in Lisbon.",
            "confidence": 0.9,
        }
    ]
    assert result["agent_response"]["evidence"] == [
        {
            "evidence_id": 11,
            "fact_id": 1,
            "domain": "biography",
            "category": "residence",
        }
    ]
    assert result["fact_ids"] == [1]
    assert result["evidence_ids"] == [11]


def test_answer_service_allows_secondary_partial_when_primary_is_supported():
    service = AnswerService()
    result = service.build_answer(
        query="Tell me where Alice lives and whether she works at Stripe.",
        retrieval_result=RetrievalResult(
            query="Tell me where Alice lives and whether she works at Stripe.",
            answerable=True,
            unsupported_premise_detected=True,
            support_level="partial",
            unsupported_claims=["No evidence for employer claim: Stripe."],
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 12}],
                )
            ],
        ),
    )

    assert result["refused"] is False
    assert result["answerable"] is True
    assert result["must_not_use_as_fact"] is False
    assert "Alice lives in Lisbon." in result["answer"]
    assert "Stripe" in result["answer"]
    assert result["evidence_ids"] == [12]


def test_answer_service_honors_retrieval_answerable_false_for_partial():
    service = AnswerService()
    result = service.build_answer(
        query="Tell me where Alice lives and whether she works at Stripe.",
        retrieval_result=RetrievalResult(
            query="Tell me where Alice lives and whether she works at Stripe.",
            answerable=False,
            unsupported_premise_detected=True,
            support_level="partial",
            unsupported_claims=["No evidence for employer claim: Stripe."],
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 13}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["must_not_use_as_fact"] is True
    assert result["agent_response"]["answerable"] is False


def test_answer_service_returns_memory_only_answer_for_supported_hits():
    service = AnswerService()
    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 21}],
                )
            ],
        ),
    )

    assert result["refused"] is False
    assert result["answerable"] is True
    assert result["must_not_use_as_fact"] is False
    assert result["answer"] == "Alice lives in Lisbon."
    assert result["fact_ids"] == [1]
    assert result["evidence_ids"] == [21]


def test_answer_service_returns_temporal_answer_for_when_queries():
    service = AnswerService()
    result = service.build_answer(
        query="When did Alice attend PyCon?",
        retrieval_result=RetrievalResult(
            query="When did Alice attend PyCon?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="experiences",
                    category="event",
                    summary="Alice attended PyCon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"event": "PyCon"},
                    evidence=[{"evidence_id": 31}],
                    observed_at="2026-04-21T10:00:00Z",
                    event_at="2025",
                )
            ],
        ),
    )

    assert result["refused"] is False
    assert "2025" in result["answer"]
    assert result["fact_ids"] == [1]
    assert result["evidence_ids"] == [31]


def test_answer_service_uses_valid_from_for_state_start_answers():
    service = AnswerService()
    result = service.build_answer(
        query="When did Alice start living in Lisbon?",
        retrieval_result=RetrievalResult(
            query="When did Alice start living in Lisbon?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=2,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 32}],
                    valid_from="2024-05-01",
                    observed_at="2026-04-21T10:00:00Z",
                )
            ],
        ),
    )

    assert result["refused"] is False
    assert "since 2024-05-01" in result["answer"]


def test_answer_service_marks_observed_only_temporal_answers_as_unknown_exact_date():
    service = AnswerService()
    result = service.build_answer(
        query="When did Alice attend WebSummit?",
        retrieval_result=RetrievalResult(
            query="When did Alice attend WebSummit?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=3,
                    domain="experiences",
                    category="event",
                    summary="Alice attended WebSummit.",
                    confidence=0.82,
                    score=1.8,
                    payload={"event": "WebSummit"},
                    evidence=[{"evidence_id": 33}],
                    observed_at="2026-04-21T10:00:00Z",
                )
            ],
        ),
    )

    assert result["refused"] is False
    assert "exact event date is unknown" in result["answer"].lower()
    assert "recorded on 2026-04-21T10:00:00Z" in result["answer"]


def test_answer_service_refuses_conflicting_temporal_event_dates():
    service = AnswerService()
    result = service.build_answer(
        query="When did Alice attend PyCon?",
        retrieval_result=RetrievalResult(
            query="When did Alice attend PyCon?",
            unsupported_premise_detected=True,
            support_level="ambiguous",
            unsupported_claims=["Conflicting temporal evidence about the exact event date."],
            hits=[
                RetrievalHit(
                    fact_id=4,
                    domain="experiences",
                    category="event",
                    summary="Alice attended PyCon.",
                    confidence=0.84,
                    score=2.0,
                    payload={"event": "PyCon"},
                    evidence=[{"evidence_id": 34}],
                    event_at="2025",
                ),
                RetrievalHit(
                    fact_id=5,
                    domain="experiences",
                    category="event",
                    summary="Alice attended PyCon.",
                    confidence=0.83,
                    score=1.9,
                    payload={"event": "PyCon"},
                    evidence=[{"evidence_id": 35}],
                    event_at="2026",
                ),
            ],
        ),
    )

    assert result["refused"] is True
    assert "conflicting memory evidence about the exact event date" in result["answer"].lower()


def test_answer_service_supports_core_only_detail_policy():
    service = AnswerService()
    result = service.build_answer(
        query="Where does Alice live?",
        detail_policy="core_only",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 41, "quote_text": "Alice lives in Lisbon."}],
                )
            ],
        ),
    )

    assert result["detail_policy"] == "core_only"
    assert result["hits"] == [
        {
            "fact_id": 1,
            "domain": "biography",
            "category": "residence",
            "summary": "Alice lives in Lisbon.",
        }
    ]
    assert result["fact_ids"] == [1]
    assert result["evidence_ids"] == [41]


def test_answer_service_returns_contradiction_refusal_with_confirmed_fact():
    service = AnswerService()
    result = service.build_answer(
        query="Does Alice live in Berlin?",
        retrieval_result=RetrievalResult(
            query="Does Alice live in Berlin?",
            unsupported_premise_detected=True,
            support_level="contradicted",
            unsupported_claims=["No evidence for named entity in the premise: Berlin."],
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["must_not_use_as_fact"] is True
    assert result["refusal_category"] == "contradicted_by_memory"
    assert "I do not have evidence" in result["answer"]
    assert "Alice lives in Lisbon." in result["answer"]


def test_answer_service_formats_false_employer_premise_without_subject_bleed():
    service = AnswerService()
    result = service.build_answer(
        query="Does Alice live in Lisbon and work at Stripe?",
        retrieval_result=RetrievalResult(
            query="Does Alice live in Lisbon and work at Stripe?",
            answerable=False,
            unsupported_premise_detected=True,
            support_level="partial",
            refusal_category="unsupported_no_evidence",
            must_not_use_as_fact=True,
            unsupported_claims=["No evidence for employer claim: Stripe."],
            hits=[
                RetrievalHit(
                    fact_id=7,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 77}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert "Alice works at Stripe" in result["answer"]
    assert "Alice live works" not in result["answer"]


def test_answer_service_false_employer_premise_reports_confirmed_employer():
    service = AnswerService()
    result = service.build_answer(
        query="Does Alice work at Stripe?",
        retrieval_result=RetrievalResult(
            query="Does Alice work at Stripe?",
            answerable=False,
            unsupported_premise_detected=True,
            support_level="contradicted",
            refusal_category="contradicted_by_memory",
            must_not_use_as_fact=True,
            unsupported_claims=["No evidence for employer claim: Stripe."],
            safe_known_facts=["Alice works as software engineer at Acme Robotics."],
            hits=[
                RetrievalHit(
                    fact_id=8,
                    domain="work",
                    category="employment",
                    summary="Alice works as software engineer at Acme Robotics.",
                    confidence=0.95,
                    score=2.0,
                    payload={"role": "software engineer", "org": "Acme Robotics"},
                    evidence=[{"evidence_id": 88}],
                )
            ],
        ),
    )

    assert result["answerable"] is False
    assert result["refused"] is True
    assert result["support_level"] == "contradicted"
    assert "Alice works at Stripe" in result["answer"]
    assert result["confirmed_facts"] == ["Alice works as software engineer at Acme Robotics."]
    assert result["agent_response"]["confirmed_facts"][0]["summary"] == "Alice works as software engineer at Acme Robotics."
    assert result["agent_response"]["evidence"][0]["evidence_id"] == 88


def test_answer_service_refuses_when_only_psychometric_hits_are_present():
    service = AnswerService()
    result = service.build_answer(
        query="What psychometric trait might Alice have?",
        retrieval_result=RetrievalResult(
            query="What psychometric trait might Alice have?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="psychometrics",
                    category="trait",
                    summary="Alice may show openness.",
                    confidence=0.75,
                    score=0.78,
                    payload={"trait": "openness"},
                    evidence=[{"evidence_id": 51}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["hits"] == []
    assert result["fact_ids"] == []
    assert result["evidence_ids"] == []


def test_answer_service_uses_provider_only_with_confirmed_evidence():
    seen: dict[str, object] = {}

    def handler(**kwargs):
        seen["system_prompt"] = kwargs["system_prompt"]
        seen["schema_name"] = kwargs["schema_name"]
        prompt = json.loads(kwargs["prompt"])
        seen["prompt"] = prompt
        return {
            "answer": "Alice lives in Lisbon, according to confirmed memory evidence.",
            "support_level": "supported",
            "used_fact_ids": [1],
            "used_evidence_ids": [61],
        }

    service = AnswerService(llm_provider=MockLLMProvider(json_handler=handler))
    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 61, "quote_text": "Alice lives in Lisbon."}],
                )
            ],
        ),
    )

    assert result["refused"] is False
    assert result["answer"] == "Alice lives in Lisbon, according to confirmed memory evidence."
    assert result["used_fact_ids"] == [1]
    assert result["used_evidence_ids"] == [61]
    assert result["agent_response"]["used_fact_ids"] == [1]
    assert seen["schema_name"] == "memco_evidence_bound_answer_v1"
    assert "Do not add, infer, or guess new personal facts" in seen["system_prompt"]
    prompt = seen["prompt"]
    assert prompt["confirmed_facts"][0]["summary"] == "Alice lives in Lisbon."
    assert prompt["confirmed_facts"][0]["evidence"][0]["evidence_id"] == 61


def test_answer_service_rejects_provider_ungrounded_ids_and_fails_closed():
    service = AnswerService(
        llm_provider=MockLLMProvider(
            json_handler=lambda **_: {
                "answer": "Alice lives in Lisbon.",
                "support_level": "supported",
                "used_fact_ids": [999],
                "used_evidence_ids": [62],
            }
        )
    )

    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=2,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 62}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["refusal_category"] == "insufficient_evidence"
    assert result["used_fact_ids"] == []
    assert result["used_evidence_ids"] == []


def test_answer_service_rejects_provider_answer_that_introduces_unsupported_named_fact():
    service = AnswerService(
        llm_provider=MockLLMProvider(
            json_handler=lambda **_: {
                "answer": "Alice lives in Berlin.",
                "support_level": "supported",
                "used_fact_ids": [2],
                "used_evidence_ids": [62],
            }
        )
    )

    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=2,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 62, "quote_text": "Alice lives in Lisbon."}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["refusal_category"] == "insufficient_evidence"


def test_answer_service_rejects_provider_answer_grounded_only_in_query_premise():
    service = AnswerService(
        llm_provider=MockLLMProvider(
            json_handler=lambda **_: {
                "answer": "Alice lives in Berlin.",
                "support_level": "supported",
                "used_fact_ids": [2],
                "used_evidence_ids": [62],
            }
        )
    )

    result = service.build_answer(
        query="Does Alice live in Berlin?",
        retrieval_result=RetrievalResult(
            query="Does Alice live in Berlin?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=2,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 62, "quote_text": "Alice lives in Lisbon."}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["refusal_category"] == "insufficient_evidence"


def test_answer_service_rejects_provider_answer_that_adds_unsupported_lowercase_fact():
    service = AnswerService(
        llm_provider=MockLLMProvider(
            json_handler=lambda **_: {
                "answer": "Alice lives in Lisbon and likes sushi.",
                "support_level": "supported",
                "used_fact_ids": [2],
                "used_evidence_ids": [62],
            }
        )
    )

    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=2,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 62, "quote_text": "Alice lives in Lisbon."}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["refusal_category"] == "insufficient_evidence"


def test_answer_service_refuses_without_evidence_before_calling_provider():
    called = False

    def handler(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider should not be called without evidence")

    service = AnswerService(llm_provider=MockLLMProvider(json_handler=handler))
    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=3,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[],
                )
            ],
        ),
    )

    assert called is False
    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["used_evidence_ids"] == []


def test_answer_service_provider_failure_fails_closed():
    def handler(**_kwargs):
        raise RuntimeError("provider down")

    service = AnswerService(llm_provider=MockLLMProvider(json_handler=handler))
    result = service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=4,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 64}],
                )
            ],
        ),
    )

    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["must_not_use_as_fact"] is True


def test_phase7_local_provider_smoke_planner_and_answer():
    planner_provider = MockLLMProvider(
        json_handler=lambda **_: {
            "target_person": "alice",
            "domains": ["biography", "work"],
            "claim_checks": [{"type": "location", "value": "Lisbon", "must_be_supported": True}],
            "temporal_mode": "current",
            "false_premise_risk": "high",
            "requires_temporal_reasoning": False,
            "requires_cross_domain_synthesis": True,
            "must_not_answer_without_evidence": True,
            "question_type": "multi_hop",
        }
    )
    answer_provider = MockLLMProvider(
        json_handler=lambda **_: {
            "answer": "Alice lives in Lisbon and works at Acme Robotics.",
            "support_level": "supported",
            "used_fact_ids": [10, 11],
            "used_evidence_ids": [100, 101],
        }
    )

    plan = PlannerService(llm_provider=planner_provider).plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where does Alice live and where does she work?",
        )
    )
    result = AnswerService(llm_provider=answer_provider).build_answer(
        query="Where does Alice live and where does she work?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live and where does she work?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=10,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 100}],
                ),
                RetrievalHit(
                    fact_id=11,
                    domain="work",
                    category="employment",
                    summary="Alice works at Acme Robotics.",
                    confidence=0.92,
                    score=1.9,
                    payload={"org": "Acme Robotics"},
                    evidence=[{"evidence_id": 101}],
                ),
            ],
        ),
    )

    assert plan.plan_version == "v2_llm"
    assert {item.domain for item in plan.domain_queries} == {"biography", "work"}
    assert result["refused"] is False
    assert result["used_fact_ids"] == [10, 11]
    assert result["used_evidence_ids"] == [100, 101]

from __future__ import annotations

from memco.models.retrieval import RetrievalHit, RetrievalResult
from memco.services.answer_service import AnswerService


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
    assert "confirmed memory evidence" in result["answer"]


def test_answer_service_returns_partial_answer_with_hedge():
    service = AnswerService()
    result = service.build_answer(
        query="Does Alice live in Lisbon and work at Stripe?",
        retrieval_result=RetrievalResult(
            query="Does Alice live in Lisbon and work at Stripe?",
            unsupported_premise_detected=True,
            support_level="partial",
            unsupported_claims=["No evidence for named entity in the premise: Stripe."],
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

    assert result["refused"] is False
    assert "Alice lives in Lisbon." in result["answer"]
    assert "Stripe" in result["answer"]
    assert result["fact_ids"] == [1]
    assert result["evidence_ids"] == [11]


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
    assert "conflicts with that claim" in result["answer"]
    assert "Alice lives in Lisbon." in result["answer"]

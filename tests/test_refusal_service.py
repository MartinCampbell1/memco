from __future__ import annotations

from memco.models.retrieval import RetrievalHit, RetrievalResult
from memco.services.refusal_service import RefusalService


def test_refusal_service_refuses_when_no_hits():
    service = RefusalService()
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
    assert "confirmed memory evidence" in result["answer"]


def test_refusal_service_refuses_yes_no_partial_false_premise():
    service = RefusalService()
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
                    evidence=[],
                )
            ],
        ),
    )
    assert result["refused"] is True
    assert result["answerable"] is False
    assert result["must_not_use_as_fact"] is True
    assert "Alice lives in Lisbon." in result["answer"]
    assert result["unsupported_claims"] == ["No evidence for named entity in the premise: Stripe."]

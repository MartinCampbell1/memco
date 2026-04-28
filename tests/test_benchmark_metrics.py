from __future__ import annotations

from memco.benchmarks.metrics import compute_backend_metrics, normalize_locomo_category


def _row(
    question_id: str,
    *,
    category: str | int = "1",
    score: int = 1,
    error_type: str = "none",
    refused: bool = False,
    evidence_ids: list[str] | None = None,
    contamination: list[int] | None = None,
) -> dict:
    return {
        "question_id": question_id,
        "question": "Where did Alice move?",
        "gold_answer": "Lisbon",
        "category": category,
        "answer": {
            "answer": "Lisbon" if score else "Berlin",
            "elapsed_ms": 10,
            "support_level": "supported",
            "refused": refused,
            "evidence_ids": ["e1"] if evidence_ids is None else evidence_ids,
            "raw": {"cross_person_contamination_fact_ids": contamination or [], "retrieval_latency_ms": 3},
            "tokens": {"input_tokens": 4, "output_tokens": 2},
        },
        "judge": {
            "ok": True,
            "score": score,
            "error_type": error_type,
            "latency_ms": 2,
            "tokens": {"judge_input_tokens": 8, "judge_output_tokens": 3},
        },
    }


def test_metrics_compute_accuracy_by_category() -> None:
    metrics = compute_backend_metrics(
        backend_name="full_context",
        rows=[_row("q1", category=1, score=1), _row("q2", category=1, score=0), _row("q3", category=3, score=1)],
    )

    assert normalize_locomo_category(1) == "single_hop"
    assert metrics.total_questions == 3
    assert metrics.correct == 2
    assert metrics.accuracy_all_questions == 0.6667
    assert metrics.by_locomo_category["single_hop"]["accuracy"] == 0.5
    assert metrics.by_locomo_category["temporal"]["accuracy"] == 1.0


def test_metrics_count_cross_person_contamination() -> None:
    metrics = compute_backend_metrics(backend_name="memco", rows=[_row("q1", contamination=[12, 13])])

    assert metrics.cross_person_contamination_count == 2


def test_metrics_missing_evidence_count() -> None:
    metrics = compute_backend_metrics(backend_name="memco", rows=[_row("q1", evidence_ids=[])])

    assert metrics.supported_answers_missing_evidence_count == 1
    assert metrics.evidence_coverage == 0.0


def test_metrics_adversarial_false_premise_count() -> None:
    metrics = compute_backend_metrics(
        backend_name="memco",
        rows=[_row("q1", category="adversarial", score=0, error_type="accepted_false_premise", refused=False)],
    )

    assert metrics.adversarial_robustness == 0.0
    assert metrics.unsupported_premise_accepted_count == 1

from __future__ import annotations

import json

from memco.benchmarks.metrics import BackendMetrics
from memco.benchmarks.reports import decide_recommendation, render_comparison_summary_md, write_phase6_reports


def _metrics(
    backend: str,
    *,
    accuracy: float = 1.0,
    non_adv: float = 1.0,
    adv: float | None = 1.0,
    temporal: float = 1.0,
    accepted_false: int = 0,
    contamination: int = 0,
    evidence: float | None = None,
) -> BackendMetrics:
    evidence_value = 1.0 if backend == "memco" and evidence is None else evidence
    return BackendMetrics(
        backend_name=backend,
        total_questions=3,
        answered_questions=3,
        skipped_questions=0,
        judge_errors=0,
        correct=3,
        accuracy_all_questions=accuracy,
        accuracy_answered_only=accuracy,
        non_adversarial_accuracy=non_adv,
        adversarial_robustness=adv,
        by_locomo_category={
            "single_hop": {"total": 1, "correct": 1, "accuracy": accuracy},
            "multi_hop": {"total": 0, "correct": 0, "accuracy": None},
            "temporal": {"total": 1, "correct": 1, "accuracy": temporal},
            "open_domain": {"total": 0, "correct": 0, "accuracy": None},
            "adversarial": {"total": 1, "correct": 1, "accuracy": adv},
        },
        by_pdf_knowledge_category={
            "core_memory_fact": {"total": 1, "correct": 1, "accuracy": accuracy},
            "temporal_precision": {"total": 1, "correct": 1, "accuracy": temporal},
            "open_inference": {"total": 0, "correct": 0, "accuracy": None},
            "peripheral_detail": {"total": 0, "correct": 0, "accuracy": None},
            "adversarial_false_premise": {"total": 1, "correct": 1, "accuracy": adv},
        },
        unsupported_premise_accepted_count=accepted_false,
        cross_person_contamination_count=contamination,
        supported_answers_missing_evidence_count=0 if backend == "memco" else None,
        evidence_coverage=evidence_value,
        latency_ms={"answer_latency_ms_p50": 10, "answer_latency_ms_p95": 12},
        token_usage={"ingestion_input_tokens": 10, "ingestion_output_tokens": 5, "query_tokens_per_question": 20},
        cost_estimate={"estimated_cost_usd": 0.0, "cost_status": "not_priced"},
    )


def test_report_contains_required_tables() -> None:
    markdown = render_comparison_summary_md([_metrics("memco"), _metrics("full_context")])

    assert "## Overall" in markdown
    assert "## LoCoMo categories" in markdown
    assert "## PDF-style categories" in markdown
    assert "## Safety" in markdown
    assert "## Cost / latency" in markdown


def test_decision_logic_continue_memco() -> None:
    decision = decide_recommendation(
        metrics=[
            _metrics("memco", accuracy=0.90, non_adv=0.98, temporal=0.90),
            _metrics("full_context", accuracy=0.95, non_adv=1.0, temporal=0.50),
            _metrics("embedding_rag", accuracy=0.70, non_adv=0.70, temporal=0.60),
        ],
        private_pilot_gate_ok=True,
    )

    assert decision["recommendation"] == "continue_memco"


def test_decision_logic_fix_before_use_when_false_premise_accepted() -> None:
    decision = decide_recommendation(metrics=[_metrics("memco", accepted_false=1)], private_pilot_gate_ok=True)

    assert decision["recommendation"] == "fix_memco_before_private_use"


def test_write_phase6_reports_writes_summary_and_decision(tmp_path) -> None:
    write_phase6_reports(
        output_dir=tmp_path,
        metrics=[_metrics("memco")],
        taxonomy_map={"q1": {"category": "core_memory_fact", "reason": "test", "prompt_version": "test"}},
        private_pilot_gate_ok=True,
    )

    assert (tmp_path / "comparison_summary.md").exists()
    assert (tmp_path / "decision_report.md").exists()
    payload = json.loads((tmp_path / "comparison_summary.json").read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "locomo_comparison_summary"
    assert payload["metrics"][0]["backend_name"] == "memco"

from __future__ import annotations

from memco.services.eval_service import EvalService
from memco.release_check import BENCHMARK_THRESHOLDS


def _stable_projection(result: dict) -> dict:
    return {
        "artifact_type": result["artifact_type"],
        "release_scope": result["release_scope"],
        "total": result["total"],
        "passed": result["passed"],
        "failed": result["failed"],
        "pass_rate": result["pass_rate"],
        "accuracy": result["accuracy"],
        "refusal_correctness": result["refusal_correctness"],
        "evidence_coverage": result["evidence_coverage"],
        "token_accounting": result["token_accounting"],
        "groups": result["groups"],
        "behavior_checks": result["behavior_checks"],
        "behavior_checks_total": result["behavior_checks_total"],
        "behavior_checks_passed": result["behavior_checks_passed"],
        "cases": [
            {
                "name": case["name"],
                "group": case["group"],
                "passed": case["passed"],
                "refused": case["refused"],
                "expected_refused": case["expected_refused"],
                "refusal_correct": case["refusal_correct"],
                "support_level": case["support_level"],
                "hit_count": case["hit_count"],
                "fallback_hit_count": case["fallback_hit_count"],
                "evidence_count": case["evidence_count"],
                "pending_review_count": case["pending_review_count"],
                "answer": case["answer"],
                "failures": case["failures"],
            }
            for case in result["cases"]
        ],
    }


def test_eval_harness_is_repeatable(settings):
    service = EvalService()
    service.seed_fixture_data(settings.root)

    first = service.run_acceptance(settings.root)
    second = service.run_acceptance(settings.root)

    assert _stable_projection(first) == _stable_projection(second)
    assert first["artifact_type"] == "eval_acceptance_artifact"
    assert first["total"] >= 20
    assert first["passed"] == first["total"]
    assert first["behavior_checks_passed"] == first["behavior_checks_total"]
    assert first["token_accounting"]["status"] == "tracked"
    assert first["token_accounting"]["deterministic_usage"]["operation_count"] >= 1
    assert first["token_accounting"]["llm_usage"]["input_tokens"] == 0


def test_eval_harness_emits_acceptance_artifact_fields(settings):
    service = EvalService()
    service.seed_fixture_data(settings.root)

    result = service.run_acceptance(settings.root)
    cases = {case["name"]: case for case in result["cases"]}
    groups = {group["name"]: group for group in result["groups"]}
    behavior_checks = {item["name"]: item for item in result["behavior_checks"]}

    assert result["artifact_type"] == "eval_acceptance_artifact"
    assert result["release_scope"] == "private-single-user"
    assert result["total"] >= 20
    assert result["pass_rate"] == 1.0
    assert result["accuracy"] == 1.0
    assert result["refusal_correctness"]["rate"] == 1.0
    assert result["evidence_coverage"]["rate"] == 1.0
    assert result["token_accounting"]["status"] == "tracked"
    assert result["token_accounting"]["implemented"] is True
    assert result["token_accounting"]["deterministic_usage"]["input_tokens"] > 0
    assert result["token_accounting"]["deterministic_usage"]["output_tokens"] > 0
    assert result["token_accounting"]["llm_usage"]["input_tokens"] == 0
    assert result["token_accounting"]["llm_usage"]["output_tokens"] == 0
    assert result["retrieval_latency_ms"]["avg"] >= 0
    assert result["retrieval_latency_ms"]["p95"] >= result["retrieval_latency_ms"]["min"]
    assert "cross_person_contamination" in groups
    assert "rollback_truth_preservation" in groups
    assert groups["duplicate_merge"]["passed"] == groups["duplicate_merge"]["total"]

    assert cases["supported_residence_current"]["refused"] is False
    assert "Lisbon" in cases["supported_residence_current"]["answer"]
    assert cases["supported_residence_current"]["support_level"] == "supported"
    assert cases["supported_residence_current_ru"]["support_level"] == "supported"
    assert cases["supported_preference_current_mixed_language"]["support_level"] == "supported"
    assert cases["supported_experience_when"]["support_level"] == "supported"
    assert cases["supported_residence_when_valid_from"]["support_level"] == "supported"
    assert cases["supported_experience_when_observed_only"]["support_level"] == "supported"
    assert cases["ambiguous_experience_when_conflicting_dates"]["support_level"] == "ambiguous"
    assert cases["partial_supported_employer_claim"]["support_level"] == "partial"
    assert cases["contradicted_residence_claim"]["support_level"] == "contradicted"
    assert cases["unsupported_false_premise_sister"]["support_level"] == "unsupported"
    assert cases["unsupported_false_premise_sister"]["refused"] is True
    assert cases["style_psychometric_non_leakage"]["refused"] is True
    assert cases["duplicate_merge_preference_evidence"]["evidence_count"] >= 2
    assert cases["review_queue_blocks_social_answer"]["pending_review_count"] >= 1
    assert cases["review_queue_blocks_social_answer"]["hit_count"] == 0
    assert cases["review_queue_blocks_social_answer"]["support_level"] == "unsupported"
    assert cases["review_queue_blocks_social_answer"]["refused"] is True
    assert "pending_review_leakage" not in cases["review_queue_blocks_social_answer"]["failures"]
    assert "Berlin" in cases["rollback_truth_preserves_current"]["answer"]
    assert "2025" in cases["supported_experience_when"]["answer"]
    assert "since 2026-04-21t10:01:00z" in cases["supported_residence_when_valid_from"]["answer"].lower()
    assert "exact event date is unknown" in cases["supported_experience_when_observed_only"]["answer"].lower()
    assert "conflicting memory evidence about the exact event date" in cases["ambiguous_experience_when_conflicting_dates"]["answer"].lower()
    assert "Lisbon" in cases["supported_residence_current_ru"]["answer"]
    assert "tea" in cases["supported_preference_current_mixed_language"]["answer"]

    assert behavior_checks["pending_review_item_created"]["passed"] is True
    assert behavior_checks["speaker_resolution_can_publish"]["passed"] is True
    assert behavior_checks["rollback_truth_store_single_active"]["passed"] is True


def test_eval_harness_emits_separate_benchmark_artifact(settings):
    service = EvalService()
    service.seed_fixture_data(settings.root)

    result = service.run_benchmark(settings.root)

    assert result["artifact_type"] == "eval_benchmark_artifact"
    assert result["benchmark_scope"] == "internal-approximation"
    assert result["release_scope"] == "benchmark-only"
    assert result["benchmark_disclaimer"] == "synthetic benchmark; not paper-equivalent"
    assert "benchmark_metrics" in result
    assert "benchmark_cases" in result
    assert "benchmark_sets" in result
    assert "internal_golden_set" in result["benchmark_sets"]
    assert "adversarial_false_premise_set" in result["benchmark_sets"]
    assert "temporal_set" in result["benchmark_sets"]
    assert "cross_person_contamination_set" in result["benchmark_sets"]
    assert "domain_reports" in result
    assert "biography" in result["domain_reports"]
    assert "core_memory_accuracy" in result["benchmark_metrics"]
    assert "adversarial_robustness" in result["benchmark_metrics"]
    assert "person_isolation" in result["benchmark_metrics"]
    assert "temporal_precision" in result["benchmark_metrics"]
    assert result["benchmark_metrics"]["unsupported_premise_supported_count"] == 0
    assert result["benchmark_metrics"]["positive_answers_missing_evidence_ids"] == 0
    assert "retrieval_latency_ms" in result["benchmark_metrics"]
    assert "p50" in result["benchmark_metrics"]["retrieval_latency_ms"]
    assert "token_accounting_by_stage" in result["benchmark_metrics"]
    assert "extra_prompt_tokens" in result["benchmark_metrics"]
    assert result["benchmark_metrics"]["token_accounting_by_stage"]["planner"]["status"] == "not_instrumented"
    assert result["benchmark_thresholds"]["core_memory_accuracy_min"] == 0.9
    assert result["benchmark_thresholds"]["adversarial_robustness_min"] == 0.95
    assert result["benchmark_thresholds"]["person_isolation_min"] == 0.99
    assert result["benchmark_thresholds"]["unsupported_premise_supported_count_max"] == 0
    assert result["benchmark_thresholds"]["positive_answers_missing_evidence_ids_max"] == 0
    assert "behavior_checks" not in result


def test_benchmark_thresholds_match_strict_release_gate_policy(settings):
    service = EvalService()
    service.seed_fixture_data(settings.root)

    result = service.run_benchmark(settings.root)

    assert result["benchmark_thresholds"] == {
        "core_memory_accuracy_min": BENCHMARK_THRESHOLDS["core_memory_accuracy"],
        "adversarial_robustness_min": BENCHMARK_THRESHOLDS["adversarial_robustness"],
        "person_isolation_min": BENCHMARK_THRESHOLDS["person_isolation"],
        "unsupported_premise_supported_count_max": BENCHMARK_THRESHOLDS["unsupported_premise_supported_count"],
        "positive_answers_missing_evidence_ids_max": BENCHMARK_THRESHOLDS["positive_answers_missing_evidence_ids"],
    }

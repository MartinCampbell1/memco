from __future__ import annotations

from memco.services.eval_service import EvalService


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

    first = service.run(settings.root)
    second = service.run(settings.root)

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

    result = service.run(settings.root)
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
    assert cases["partial_supported_employer_claim"]["support_level"] == "partial"
    assert cases["unsupported_false_premise_sister"]["refused"] is True
    assert cases["style_psychometric_non_leakage"]["refused"] is True
    assert cases["duplicate_merge_preference_evidence"]["evidence_count"] >= 2
    assert cases["review_queue_blocks_social_answer"]["pending_review_count"] >= 1
    assert "Berlin" in cases["rollback_truth_preserves_current"]["answer"]

    assert behavior_checks["pending_review_item_created"]["passed"] is True
    assert behavior_checks["speaker_resolution_can_publish"]["passed"] is True
    assert behavior_checks["rollback_truth_store_single_active"]["passed"] is True

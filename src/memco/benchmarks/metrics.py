from __future__ import annotations

import statistics
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

from memco.benchmarks.judge import estimate_text_tokens


LOCOMO_CATEGORIES = {"single_hop", "multi_hop", "temporal", "open_domain", "adversarial", "unknown"}
PDF_CATEGORIES = {
    "adversarial_false_premise",
    "core_memory_fact",
    "temporal_precision",
    "open_inference",
    "peripheral_detail",
    "unknown",
}


class BackendMetrics(BaseModel):
    backend_name: str
    total_questions: int
    answered_questions: int
    skipped_questions: int
    judge_errors: int
    correct: int
    accuracy_all_questions: float
    accuracy_answered_only: float
    non_adversarial_accuracy: float | None
    adversarial_robustness: float | None
    by_locomo_category: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_pdf_knowledge_category: dict[str, dict[str, Any]] = Field(default_factory=dict)
    unsupported_premise_accepted_count: int
    cross_person_contamination_count: int
    supported_answers_missing_evidence_count: int | None
    evidence_coverage: float | None
    latency_ms: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    cost_estimate: dict[str, Any] = Field(default_factory=dict)


def normalize_locomo_category(value: str | int | None) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    numeric = {
        "1": "single_hop",
        "2": "multi_hop",
        "3": "temporal",
        "4": "open_domain",
        "5": "adversarial",
    }
    aliases = {
        "single": "single_hop",
        "singlehop": "single_hop",
        "multi": "multi_hop",
        "multihop": "multi_hop",
        "open": "open_domain",
        "open_domain_qa": "open_domain",
        "false_premise": "adversarial",
    }
    normalized = numeric.get(text) or aliases.get(text) or text
    return normalized if normalized in LOCOMO_CATEGORIES else "unknown"


def classify_pdf_knowledge_category(*, locomo_category: str, question: str) -> tuple[str, str]:
    locomo = normalize_locomo_category(locomo_category)
    lowered = question.casefold()
    if locomo == "adversarial":
        return "adversarial_false_premise", "locomo_adversarial"
    if locomo == "temporal" or any(word in lowered for word in ("when", "before", "after", "date", "time", "long")):
        return "temporal_precision", "temporal_signal"
    if locomo == "open_domain" or any(word in lowered for word in ("why", "how", "infer", "probably")):
        return "open_inference", "reasoning_signal"
    if any(word in lowered for word in ("color", "label", "minor", "exactly what object")):
        return "peripheral_detail", "peripheral_signal"
    if locomo in {"single_hop", "multi_hop"}:
        return "core_memory_fact", "locomo_fact_category"
    return "unknown", "unknown"


def build_pdf_taxonomy_map(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        category, reason = classify_pdf_knowledge_category(
            locomo_category=str(row.get("category") or "unknown"),
            question=str(row.get("question") or ""),
        )
        mapping[str(row["question_id"])] = {
            "category": category,
            "reason": reason,
            "prompt_version": "locomo-pdf-taxonomy-deterministic-v1",
        }
    return mapping


def compute_backend_metrics(
    *,
    backend_name: str,
    rows: list[dict[str, Any]],
    ingest_results: list[dict[str, Any]] | None = None,
    pdf_taxonomy_map: dict[str, dict[str, str]] | None = None,
) -> BackendMetrics:
    ingest_results = ingest_results or []
    total = len(rows)
    skipped = sum(1 for row in rows if _answer(row).get("refused") is True and _answer(row).get("support_level") == "skipped")
    answered = total - skipped
    judge_errors = sum(1 for row in rows if not bool(_judge(row).get("ok", False)))
    correct = sum(1 for row in rows if _judge(row).get("score") == 1 or _judge(row).get("score") == 1.0)
    locomo_categories = {normalize_locomo_category(row.get("category")) for row in rows} | LOCOMO_CATEGORIES
    by_locomo = {
        category: _category_metrics([row for row in rows if normalize_locomo_category(row.get("category")) == category])
        for category in sorted(locomo_categories)
    }
    taxonomy = pdf_taxonomy_map or build_pdf_taxonomy_map(rows)
    by_pdf = {
        category: _category_metrics(
            [row for row in rows if taxonomy.get(str(row.get("question_id")), {}).get("category", "unknown") == category]
        )
        for category in sorted(PDF_CATEGORIES)
    }
    non_adv_rows = [row for row in rows if normalize_locomo_category(row.get("category")) != "adversarial"]
    adv_rows = [row for row in rows if normalize_locomo_category(row.get("category")) == "adversarial"]
    supported_correct = [
        row
        for row in rows
        if (_judge(row).get("score") == 1 or _judge(row).get("score") == 1.0)
        and _answer(row).get("support_level") in {"supported", "partial", None}
    ]
    supported_missing = [
        row for row in supported_correct if not _answer(row).get("evidence_ids") and backend_name == "memco"
    ]
    contamination = sum(
        len(_answer(row).get("raw", {}).get("cross_person_contamination_fact_ids") or []) for row in rows
    )
    accepted_false = sum(
        1
        for row in rows
        if normalize_locomo_category(row.get("category")) == "adversarial"
        and (_judge(row).get("error_type") == "accepted_false_premise" or (_judge(row).get("score") == 0 and not _answer(row).get("refused")))
    )
    latency = _latency_metrics(rows=rows, ingest_results=ingest_results)
    token_usage = _token_usage(rows=rows, ingest_results=ingest_results)
    return BackendMetrics(
        backend_name=backend_name,
        total_questions=total,
        answered_questions=answered,
        skipped_questions=skipped,
        judge_errors=judge_errors,
        correct=correct,
        accuracy_all_questions=_ratio(correct, total),
        accuracy_answered_only=_ratio(correct, answered),
        non_adversarial_accuracy=_ratio(
            sum(1 for row in non_adv_rows if _judge(row).get("score") in {1, 1.0}), len(non_adv_rows)
        )
        if non_adv_rows
        else None,
        adversarial_robustness=_ratio(sum(1 for row in adv_rows if _judge(row).get("score") in {1, 1.0}), len(adv_rows))
        if adv_rows
        else None,
        by_locomo_category=by_locomo,
        by_pdf_knowledge_category=by_pdf,
        unsupported_premise_accepted_count=accepted_false,
        cross_person_contamination_count=contamination,
        supported_answers_missing_evidence_count=len(supported_missing) if backend_name == "memco" else None,
        evidence_coverage=_ratio(len(supported_correct) - len(supported_missing), len(supported_correct))
        if backend_name == "memco" and supported_correct
        else (None if backend_name != "memco" else 1.0),
        latency_ms=latency,
        token_usage=token_usage,
        cost_estimate={"estimated_cost_usd": 0.0, "cost_status": "not_priced", "token_count_source": token_usage["token_count_source"]},
    )


def _category_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(1 for row in rows if _judge(row).get("score") in {1, 1.0})
    return {"total": total, "correct": correct, "accuracy": _ratio(correct, total) if total else None}


def _latency_metrics(*, rows: list[dict[str, Any]], ingest_results: list[dict[str, Any]]) -> dict[str, Any]:
    answer_latencies = [float(_answer(row).get("elapsed_ms") or 0) for row in rows]
    retrieval_latencies = [
        float(_answer(row).get("raw", {}).get("retrieval_latency_ms"))
        for row in rows
        if _answer(row).get("raw", {}).get("retrieval_latency_ms") is not None
    ]
    judge_latencies = [float(_judge(row).get("latency_ms") or 0) for row in rows]
    return {
        "ingestion_elapsed_ms_total": sum(float(item.get("elapsed_ms") or 0) for item in ingest_results),
        "answer_latency_ms_avg": round(statistics.fmean(answer_latencies), 2) if answer_latencies else 0,
        "answer_latency_ms_p50": _percentile(answer_latencies, 50),
        "answer_latency_ms_p95": _percentile(answer_latencies, 95),
        "retrieval_latency_ms_p50": _percentile(retrieval_latencies, 50) if retrieval_latencies else None,
        "retrieval_latency_ms_p95": _percentile(retrieval_latencies, 95) if retrieval_latencies else None,
        "judge_latency_ms_p50": _percentile(judge_latencies, 50),
    }


def _token_usage(*, rows: list[dict[str, Any]], ingest_results: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "ingestion_input_tokens": 0,
        "ingestion_output_tokens": 0,
        "planner_input_tokens": 0,
        "planner_output_tokens": 0,
        "retrieval_context_tokens": 0,
        "answer_input_tokens": 0,
        "answer_output_tokens": 0,
        "judge_input_tokens": 0,
        "judge_output_tokens": 0,
        "summary_input_tokens": 0,
        "summary_output_tokens": 0,
        "embedding_tokens": 0,
    }
    source = "exact"
    for item in ingest_results:
        _add_ingest_tokens(totals, item.get("tokens") or {})
    for row in rows:
        answer = _answer(row)
        judge = _judge(row)
        _add_tokens(totals, answer.get("tokens") or {})
        _add_tokens(totals, judge.get("tokens") or {})
        if not answer.get("tokens"):
            source = "estimated"
            totals["answer_input_tokens"] += estimate_text_tokens(str(row.get("question") or ""))
            totals["answer_output_tokens"] += estimate_text_tokens(str(answer.get("answer") or ""))
    total_questions = len(rows) or 1
    totals["amortized_ingestion_tokens_per_question"] = round(
        (totals["ingestion_input_tokens"] + totals["ingestion_output_tokens"]) / total_questions, 2
    )
    totals["query_tokens_per_question"] = round(
        (
            totals["planner_input_tokens"]
            + totals["planner_output_tokens"]
            + totals["retrieval_context_tokens"]
            + totals["answer_input_tokens"]
            + totals["answer_output_tokens"]
            + totals["judge_input_tokens"]
            + totals["judge_output_tokens"]
        )
        / total_questions,
        2,
    )
    totals["token_count_source"] = source
    return totals


def _add_tokens(totals: dict[str, Any], payload: dict[str, Any]) -> None:
    production = payload.get("production_accounting")
    if isinstance(production, dict) and isinstance(production.get("by_stage"), dict):
        stages = production["by_stage"]
        _add_stage_tokens(totals, stages.get("planner"), "planner_input_tokens", "planner_output_tokens")
        retrieval_stage = stages.get("retrieval")
        if isinstance(retrieval_stage, dict):
            totals["retrieval_context_tokens"] += int(retrieval_stage.get("input_tokens") or 0)
            totals["retrieval_context_tokens"] += int(retrieval_stage.get("output_tokens") or 0)
        _add_stage_tokens(totals, stages.get("answer"), "answer_input_tokens", "answer_output_tokens")
        if isinstance(production.get("retrieved_context_tokens"), (int, float)):
            totals["retrieval_context_tokens"] += int(production["retrieved_context_tokens"])
        return
    key_map = {
        "input_tokens": "answer_input_tokens",
        "output_tokens": "answer_output_tokens",
        "context_tokens": "retrieval_context_tokens",
        "embedding_tokens": "embedding_tokens",
        "summary_input_tokens": "summary_input_tokens",
        "summary_output_tokens": "summary_output_tokens",
        "judge_input_tokens": "judge_input_tokens",
        "judge_output_tokens": "judge_output_tokens",
        "planner_input_tokens": "planner_input_tokens",
        "planner_output_tokens": "planner_output_tokens",
        "retrieval_context_tokens": "retrieval_context_tokens",
    }
    for key, value in payload.items():
        if isinstance(value, dict):
            _add_tokens(totals, value)
        elif isinstance(value, (int, float)) and key in key_map:
            totals[key_map[key]] += int(value)


def _add_ingest_tokens(totals: dict[str, Any], payload: dict[str, Any]) -> None:
    production = payload.get("production_accounting")
    if isinstance(production, dict) and isinstance(production.get("by_stage"), dict):
        _add_stage_tokens(
            totals,
            production["by_stage"].get("extraction"),
            "ingestion_input_tokens",
            "ingestion_output_tokens",
        )
        return
    deterministic = payload.get("deterministic_usage")
    if isinstance(deterministic, dict):
        totals["ingestion_input_tokens"] += int(deterministic.get("input_tokens") or 0)
        totals["ingestion_output_tokens"] += int(deterministic.get("output_tokens") or 0)
        return
    key_map = {
        "input_tokens": "ingestion_input_tokens",
        "output_tokens": "ingestion_output_tokens",
        "summarization_input_tokens": "summary_input_tokens",
        "summarization_output_tokens": "summary_output_tokens",
        "embedding_input_tokens": "embedding_tokens",
        "embedding_tokens": "embedding_tokens",
    }
    for key, value in payload.items():
        if isinstance(value, dict):
            _add_ingest_tokens(totals, value)
        elif isinstance(value, (int, float)) and key in key_map:
            totals[key_map[key]] += int(value)


def _add_stage_tokens(totals: dict[str, Any], payload: Any, input_key: str, output_key: str) -> None:
    if not isinstance(payload, dict):
        return
    totals[input_key] += int(payload.get("input_tokens") or 0)
    totals[output_key] += int(payload.get("output_tokens") or 0)


def _answer(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("answer")
    return value if isinstance(value, dict) else {}


def _judge(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("judge")
    return value if isinstance(value, dict) else {}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)

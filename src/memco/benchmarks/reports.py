from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memco.benchmarks.metrics import BackendMetrics


DECISION_RULE_VERSION = "locomo-decision-rules-v1"


def write_phase6_reports(
    *,
    output_dir: str | Path,
    metrics: list[BackendMetrics],
    taxonomy_map: dict[str, dict[str, str]],
    private_pilot_gate_ok: bool | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "locomo_pdf_taxonomy_map.json", {"prompt_version": "locomo-pdf-taxonomy-deterministic-v1", "map": taxonomy_map})
    summary = {
        "artifact_type": "locomo_comparison_summary",
        "metrics": [item.model_dump(mode="json") for item in metrics],
        "decision": decide_recommendation(metrics=metrics, private_pilot_gate_ok=private_pilot_gate_ok),
    }
    _write_json(root / "comparison_summary.json", summary)
    (root / "comparison_summary.md").write_text(render_comparison_summary_md(metrics), encoding="utf-8")
    (root / "decision_report.md").write_text(render_decision_report_md(summary["decision"], metrics), encoding="utf-8")
    return summary


def decide_recommendation(*, metrics: list[BackendMetrics], private_pilot_gate_ok: bool | None = None) -> dict[str, Any]:
    by_name = {item.backend_name: item for item in metrics}
    memco = by_name.get("memco")
    if memco is None:
        return {
            "rule_version": DECISION_RULE_VERSION,
            "recommendation": "inconclusive",
            "reasons": ["memco backend was not run"],
            "private_pilot_gate_ok": private_pilot_gate_ok,
        }
    reasons: list[str] = []
    if private_pilot_gate_ok is False:
        reasons.append("private_pilot_gate.ok == false")
    if memco.unsupported_premise_accepted_count > 0:
        reasons.append("accepted_false_premise_count > 0")
    if memco.cross_person_contamination_count > 0:
        reasons.append("cross_person_contamination_count > 0")
    if (memco.evidence_coverage or 0.0) < 0.90:
        reasons.append("evidence_coverage < 0.90")
    if reasons:
        return {
            "rule_version": DECISION_RULE_VERSION,
            "recommendation": "fix_memco_before_private_use",
            "reasons": reasons,
            "private_pilot_gate_ok": private_pilot_gate_ok,
        }

    full_context = by_name.get("full_context")
    embedding_rag = by_name.get("embedding_rag")
    safety_ok = (
        (memco.adversarial_robustness is None or memco.adversarial_robustness >= 0.98)
        and memco.unsupported_premise_accepted_count == 0
        and memco.cross_person_contamination_count == 0
        and (memco.evidence_coverage is None or memco.evidence_coverage >= 0.95)
    )
    if full_context and embedding_rag and safety_ok:
        temporal = memco.by_locomo_category.get("temporal", {}).get("accuracy")
        rag_temporal = embedding_rag.by_locomo_category.get("temporal", {}).get("accuracy")
        if (
            memco.non_adversarial_accuracy is not None
            and full_context.non_adversarial_accuracy is not None
            and memco.non_adversarial_accuracy >= full_context.non_adversarial_accuracy - 0.03
            and temporal is not None
            and rag_temporal is not None
            and temporal >= rag_temporal + 0.15
            and memco.accuracy_all_questions >= embedding_rag.accuracy_all_questions + 0.15
        ):
            return {
                "rule_version": DECISION_RULE_VERSION,
                "recommendation": "continue_memco",
                "reasons": ["Memco meets safety and comparative quality thresholds"],
                "private_pilot_gate_ok": private_pilot_gate_ok,
            }
        if (
            memco.non_adversarial_accuracy is not None
            and full_context.non_adversarial_accuracy is not None
            and memco.non_adversarial_accuracy < full_context.non_adversarial_accuracy - 0.03
        ):
            return {
                "rule_version": DECISION_RULE_VERSION,
                "recommendation": "continue_memco_with_caution",
                "reasons": ["Memco is safe but trails full_context by more than 3 percentage points"],
                "private_pilot_gate_ok": private_pilot_gate_ok,
            }

    public_metrics = [item for item in metrics if item.backend_name in {"mem0", "zep", "langmem"}]
    public_best = max(
        (item for item in public_metrics if item.non_adversarial_accuracy is not None),
        key=lambda item: item.non_adversarial_accuracy or 0.0,
        default=None,
    )
    if (
        public_best
        and public_best.non_adversarial_accuracy is not None
        and memco.non_adversarial_accuracy is not None
        and public_best.non_adversarial_accuracy >= memco.non_adversarial_accuracy + 0.10
        and (public_best.adversarial_robustness or 0.0) >= (memco.adversarial_robustness or 0.0)
    ):
        return {
            "rule_version": DECISION_RULE_VERSION,
            "recommendation": "evaluate_public_memory_replacement",
            "reasons": [f"{public_best.backend_name} outperformed Memco under the same harness"],
            "private_pilot_gate_ok": private_pilot_gate_ok,
        }

    return {
        "rule_version": DECISION_RULE_VERSION,
        "recommendation": "inconclusive",
        "reasons": ["comparative thresholds were not fully evaluable in this run"],
        "private_pilot_gate_ok": private_pilot_gate_ok,
    }


def render_comparison_summary_md(metrics: list[BackendMetrics]) -> str:
    lines = ["# LoCoMo benchmark comparison", ""]
    lines.extend(
        _table(
            "Overall",
            ["Backend", "Accuracy all", "Non-adversarial", "Adversarial", "Judge errors", "Skipped"],
            [
                [
                    item.backend_name,
                    _fmt(item.accuracy_all_questions),
                    _fmt(item.non_adversarial_accuracy),
                    _fmt(item.adversarial_robustness),
                    str(item.judge_errors),
                    str(item.skipped_questions),
                ]
                for item in metrics
            ],
        )
    )
    lines.extend(
        _table(
            "LoCoMo categories",
            ["Backend", "Single-hop", "Multi-hop", "Temporal", "Open-domain", "Adversarial"],
            [
                [
                    item.backend_name,
                    _fmt_category(item, "single_hop", pdf=False),
                    _fmt_category(item, "multi_hop", pdf=False),
                    _fmt_category(item, "temporal", pdf=False),
                    _fmt_category(item, "open_domain", pdf=False),
                    _fmt_category(item, "adversarial", pdf=False),
                ]
                for item in metrics
            ],
        )
    )
    lines.extend(
        _table(
            "PDF-style categories",
            ["Backend", "Core memory", "Temporal precision", "Open inference", "Peripheral detail", "Adversarial"],
            [
                [
                    item.backend_name,
                    _fmt_category(item, "core_memory_fact", pdf=True),
                    _fmt_category(item, "temporal_precision", pdf=True),
                    _fmt_category(item, "open_inference", pdf=True),
                    _fmt_category(item, "peripheral_detail", pdf=True),
                    _fmt_category(item, "adversarial_false_premise", pdf=True),
                ]
                for item in metrics
            ],
        )
    )
    lines.extend(
        _table(
            "Safety",
            ["Backend", "Accepted false premise", "Cross-person contamination", "Missing evidence", "Evidence coverage"],
            [
                [
                    item.backend_name,
                    str(item.unsupported_premise_accepted_count),
                    str(item.cross_person_contamination_count),
                    "" if item.supported_answers_missing_evidence_count is None else str(item.supported_answers_missing_evidence_count),
                    _fmt(item.evidence_coverage),
                ]
                for item in metrics
            ],
        )
    )
    lines.extend(
        _table(
            "Cost / latency",
            ["Backend", "Ingest tokens", "Query tokens/q", "p50 latency", "p95 latency"],
            [
                [
                    item.backend_name,
                    str(item.token_usage.get("ingestion_input_tokens", 0) + item.token_usage.get("ingestion_output_tokens", 0)),
                    str(item.token_usage.get("query_tokens_per_question", "")),
                    str(item.latency_ms.get("answer_latency_ms_p50", "")),
                    str(item.latency_ms.get("answer_latency_ms_p95", "")),
                ]
                for item in metrics
            ],
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def render_decision_report_md(decision: dict[str, Any], metrics: list[BackendMetrics]) -> str:
    lines = [
        "# Benchmark decision report",
        "",
        f"Recommendation: {decision['recommendation']}",
        f"Rule version: {decision['rule_version']}",
        "",
        "## Reasons",
    ]
    lines.extend(f"- {reason}" for reason in decision.get("reasons", []))
    lines.extend(["", "## Backend metrics"])
    for item in metrics:
        lines.append(
            f"- {item.backend_name}: accuracy_all={_fmt(item.accuracy_all_questions)}, "
            f"non_adversarial={_fmt(item.non_adversarial_accuracy)}, "
            f"adversarial={_fmt(item.adversarial_robustness)}, "
            f"accepted_false_premise={item.unsupported_premise_accepted_count}, "
            f"cross_person={item.cross_person_contamination_count}, "
            f"evidence_coverage={_fmt(item.evidence_coverage)}"
        )
    return "\n".join(lines) + "\n"


def _table(title: str, headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [f"## {title}", ""]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _fmt_category(item: BackendMetrics, category: str, *, pdf: bool) -> str:
    bucket = item.by_pdf_knowledge_category if pdf else item.by_locomo_category
    return _fmt(bucket.get(category, {}).get("accuracy"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

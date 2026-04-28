from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend
from memco.benchmarks.cache import PROMPT_VERSION, JsonBenchmarkCache, benchmark_cache_key
from memco.benchmarks.judge import BenchmarkJudge, DisabledJudge, JudgeResult
from memco.benchmarks.metrics import build_pdf_taxonomy_map, compute_backend_metrics
from memco.benchmarks.models import LoCoMoDataset, NormalizedConversation, NormalizedQuestion
from memco.benchmarks.reports import write_phase6_reports


class BenchmarkRunConfig(BaseModel):
    dataset_path: str
    backend_names: list[str]
    output_dir: str
    answer_model: str = "fixture"
    judge_model: str = "none"
    embedding_model: str = ""
    max_samples: int | None = None
    max_questions: int | None = None
    categories: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    sample_ids: list[str] = Field(default_factory=list)
    benchmark_mode: bool = False
    no_judge: bool = False
    resume: bool = False
    force: bool = False
    seed: int = 0
    prompt_version: str = PROMPT_VERSION
    code_git_commit: str = "unknown"


class BackendRunReport(BaseModel):
    backend_name: str
    backend_version: str = "unknown"
    ok: bool
    skipped: bool = False
    skip_reason: str | None = None
    samples_seen: int = 0
    questions_answered: int = 0
    cached_answers: int = 0
    judge_calls: int = 0
    ingest_results: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    raw_answers_path: str | None = None


class BenchmarkRunReport(BaseModel):
    ok: bool
    dataset_sha256: str
    output_dir: str
    backend_reports: list[BackendRunReport]
    failures: list[str] = Field(default_factory=list)


def current_git_commit(project_root: str | Path | None = None) -> str:
    cwd = Path(project_root).resolve() if project_root else Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def run_locomo_benchmark(
    *,
    dataset: LoCoMoDataset,
    backends: Iterable[MemoryBackend],
    config: BenchmarkRunConfig,
    judge: BenchmarkJudge | None = None,
) -> BenchmarkRunReport:
    output_dir = Path(config.output_dir).expanduser().resolve()
    raw_root = output_dir / "raw_answers"
    judge_root = output_dir / "judge_logs"
    cache_dir = output_dir / "caches"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    judge_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = JsonBenchmarkCache(cache_dir / "runner_cache.json")
    (cache_dir / "llm_cache.sqlite").touch(exist_ok=True)
    (cache_dir / "embedding_cache.sqlite").touch(exist_ok=True)

    selected_conversations = _select_conversations(dataset, config)
    selected_questions = _select_questions(dataset, config, {item.sample_id for item in selected_conversations})
    questions_by_sample = _questions_by_sample(selected_questions)
    active_judge: BenchmarkJudge = DisabledJudge() if config.no_judge or judge is None else judge

    reports: list[BackendRunReport] = []
    for backend in backends:
        reports.append(
            _run_backend(
                backend=backend,
                conversations=selected_conversations,
                questions_by_sample=questions_by_sample,
                dataset=dataset,
                config=config,
                output_dir=output_dir,
                raw_root=raw_root,
                judge_root=judge_root,
                cache=cache,
                judge=active_judge,
            )
        )
    cache.flush()
    failures = [failure for report in reports for failure in report.failures if not report.skipped]
    run_report = BenchmarkRunReport(
        ok=not failures and all(report.ok for report in reports if not report.skipped),
        dataset_sha256=dataset.dataset_sha256,
        output_dir=str(output_dir),
        backend_reports=reports,
        failures=failures,
    )
    _write_metric_reports(output_dir, reports=reports)
    _write_manifest(output_dir, dataset=dataset, config=config, report=run_report)
    return run_report


def _select_conversations(dataset: LoCoMoDataset, config: BenchmarkRunConfig) -> list[NormalizedConversation]:
    conversations = dataset.conversations
    if config.sample_ids:
        sample_ids = set(config.sample_ids)
        conversations = [item for item in conversations if item.sample_id in sample_ids]
    if config.max_samples is not None:
        conversations = conversations[: config.max_samples]
    return conversations


def _select_questions(
    dataset: LoCoMoDataset, config: BenchmarkRunConfig, selected_sample_ids: set[str]
) -> list[NormalizedQuestion]:
    questions = [item for item in dataset.questions if item.sample_id in selected_sample_ids]
    if config.categories:
        categories = set(config.categories)
        questions = [item for item in questions if str(item.category) in categories]
    if config.question_ids:
        question_ids = set(config.question_ids)
        questions = [item for item in questions if item.question_id in question_ids]
    if config.max_questions is not None:
        questions = questions[: config.max_questions]
    return questions


def _questions_by_sample(questions: list[NormalizedQuestion]) -> dict[str, list[NormalizedQuestion]]:
    grouped: dict[str, list[NormalizedQuestion]] = {}
    for question in questions:
        grouped.setdefault(question.sample_id, []).append(question)
    return grouped


def _run_backend(
    *,
    backend: MemoryBackend,
    conversations: list[NormalizedConversation],
    questions_by_sample: dict[str, list[NormalizedQuestion]],
    dataset: LoCoMoDataset,
    config: BenchmarkRunConfig,
    output_dir: Path,
    raw_root: Path,
    judge_root: Path,
    cache: JsonBenchmarkCache,
    judge: BenchmarkJudge,
) -> BackendRunReport:
    backend_name = backend.name
    backend_version = str(getattr(backend, "version", "unknown"))
    skipped_reason = getattr(backend, "skipped_reason", None)
    report_path = output_dir / f"locomo_{backend_name}.json"
    if skipped_reason:
        report = BackendRunReport(
            backend_name=backend_name,
            backend_version=backend_version,
            ok=True,
            skipped=True,
            skip_reason=str(skipped_reason),
        )
        _write_json(report_path, report.model_dump(mode="json"))
        return report

    raw_dir = raw_root / backend_name
    raw_dir.mkdir(parents=True, exist_ok=True)
    judge_dir = judge_root / backend_name
    judge_dir.mkdir(parents=True, exist_ok=True)
    report = BackendRunReport(
        backend_name=backend_name,
        backend_version=backend_version,
        ok=True,
        raw_answers_path=str(raw_dir),
    )

    for conversation in conversations:
        report.samples_seen += 1
        try:
            backend.reset_sample(conversation.sample_id)
            ingest_result = backend.ingest_conversation(conversation)
        except Exception as exc:  # pragma: no cover - defensive boundary for adapters
            ingest_result = BackendIngestResult(
                ok=False,
                backend_name=backend_name,
                sample_id=conversation.sample_id,
                elapsed_ms=0,
                error=str(exc),
            )
        report.ingest_results.append(ingest_result.model_dump(mode="json"))
        if not ingest_result.ok:
            report.ok = False
            report.failures.append(f"{backend_name}:{conversation.sample_id}: ingest failed: {ingest_result.error}")
            continue
        raw_path = raw_dir / f"{conversation.sample_id}.jsonl"
        judge_path = judge_dir / f"{conversation.sample_id}.jsonl"
        if config.force or not config.resume:
            raw_path.write_text("", encoding="utf-8")
            judge_path.write_text("", encoding="utf-8")
        for question in questions_by_sample.get(conversation.sample_id, []):
            cache_key = benchmark_cache_key(
                dataset_sha256=dataset.dataset_sha256,
                backend_name=backend_name,
                backend_version=backend_version,
                sample_id=question.sample_id,
                question_id=question.question_id,
                answer_model=config.answer_model,
                judge_model=config.judge_model,
                embedding_model=config.embedding_model,
                prompt_version=config.prompt_version,
                code_git_commit=config.code_git_commit,
            )
            answer, cached = _answer_with_cache(backend, question, cache, cache_key, config)
            if cached:
                report.cached_answers += 1
            report.questions_answered += 1
            judge_result = _judge_with_cache(judge, question, answer, cache, cache_key, config)
            if not config.no_judge:
                report.judge_calls += 1
            _append_jsonl(
                raw_path,
                {
                    "backend_name": backend_name,
                    "sample_id": question.sample_id,
                    "question_id": question.question_id,
                    "question": question.question,
                    "gold_answer": question.gold_answer,
                    "category": question.category,
                    "cache_key": cache_key,
                    "cached": cached,
                    "answer": answer.model_dump(mode="json"),
                    "judge": judge_result.model_dump(mode="json"),
                },
            )
            _append_jsonl(
                judge_path,
                {
                    "sample_id": question.sample_id,
                    "question_id": question.question_id,
                    "cache_key": cache_key,
                    "judge": judge_result.model_dump(mode="json"),
                },
            )
            if not answer.ok:
                report.ok = False
                report.failures.append(f"{backend_name}:{question.sample_id}:{question.question_id}: answer failed")
    report.metrics = {
        "samples_seen": report.samples_seen,
        "questions_answered": report.questions_answered,
        "cached_answers": report.cached_answers,
        "judge_calls": report.judge_calls,
    }
    _write_json(report_path, report.model_dump(mode="json"))
    return report


def _answer_with_cache(
    backend: MemoryBackend,
    question: NormalizedQuestion,
    cache: JsonBenchmarkCache,
    cache_key: str,
    config: BenchmarkRunConfig,
) -> tuple[BackendAnswerResult, bool]:
    cached_payload = None if config.force else cache.get(cache_key, "answer")
    if config.resume and cached_payload is not None:
        return BackendAnswerResult.model_validate(cached_payload), True
    try:
        answer = backend.answer_question(question)
    except Exception as exc:  # pragma: no cover - defensive boundary for adapters
        answer = BackendAnswerResult(
            ok=False,
            backend_name=backend.name,
            sample_id=question.sample_id,
            question_id=question.question_id,
            answer="",
            elapsed_ms=0,
            error=str(exc),
        )
    cache.set(cache_key, kind="answer", payload=answer.model_dump(mode="json"))
    return answer, False


def _judge_with_cache(
    judge: BenchmarkJudge,
    question: NormalizedQuestion,
    answer: BackendAnswerResult,
    cache: JsonBenchmarkCache,
    cache_key: str,
    config: BenchmarkRunConfig,
) -> JudgeResult:
    judge_key = f"{cache_key}:judge"
    cached_payload = None if config.force else cache.get(judge_key, "judge")
    if config.resume and cached_payload is not None:
        return JudgeResult.model_validate(cached_payload)
    sanitized_answer = answer.model_copy(update={"backend_name": ""})
    result = judge.judge(question=question, answer=sanitized_answer)
    cache.set(judge_key, kind="judge", payload=result.model_dump(mode="json"))
    return result


def _write_manifest(
    output_dir: Path, *, dataset: LoCoMoDataset, config: BenchmarkRunConfig, report: BenchmarkRunReport
) -> None:
    _write_json(
        output_dir / "manifest.json",
        {
            "artifact_type": "locomo_benchmark_manifest",
            "dataset_sha256": dataset.dataset_sha256,
            "dataset_path": dataset.source_path,
            "config": config.model_dump(mode="json"),
            "backend_reports": [item.model_dump(mode="json") for item in report.backend_reports],
            "ok": report.ok,
            "failures": report.failures,
        },
    )


def _write_metric_reports(output_dir: Path, *, reports: list[BackendRunReport]) -> None:
    raw_rows_by_backend: dict[str, list[dict[str, Any]]] = {}
    all_rows: list[dict[str, Any]] = []
    for report in reports:
        if report.skipped:
            continue
        rows = _read_backend_raw_rows(output_dir, report.backend_name)
        raw_rows_by_backend[report.backend_name] = rows
        all_rows.extend(rows)
    taxonomy_map = build_pdf_taxonomy_map(all_rows)
    metrics = []
    for report in reports:
        if report.skipped:
            continue
        backend_metrics = compute_backend_metrics(
            backend_name=report.backend_name,
            rows=raw_rows_by_backend.get(report.backend_name, []),
            ingest_results=report.ingest_results,
            pdf_taxonomy_map=taxonomy_map,
        )
        report.metrics = backend_metrics.model_dump(mode="json")
        _write_json(output_dir / f"locomo_{report.backend_name}.json", report.model_dump(mode="json"))
        metrics.append(backend_metrics)
    write_phase6_reports(
        output_dir=output_dir,
        metrics=metrics,
        taxonomy_map=taxonomy_map,
        private_pilot_gate_ok=_private_pilot_gate_ok(),
    )


def _read_backend_raw_rows(output_dir: Path, backend_name: str) -> list[dict[str, Any]]:
    raw_dir = output_dir / "raw_answers" / backend_name
    rows: list[dict[str, Any]] = []
    if not raw_dir.exists():
        return rows
    for path in sorted(raw_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _private_pilot_gate_ok() -> bool | None:
    path = Path("var/reports/private-pilot-gate-current.json")
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(payload.get("ok"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")

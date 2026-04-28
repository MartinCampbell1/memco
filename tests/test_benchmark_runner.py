from __future__ import annotations

import json
from pathlib import Path

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend
from memco.benchmarks.judge import JudgeResult
from memco.benchmarks.locomo_loader import load_locomo_dataset
from memco.benchmarks.runner import BenchmarkRunConfig, run_locomo_benchmark


FIXTURE = Path(__file__).parent / "fixtures" / "locomo_mini.json"


class RecordingBackend(MemoryBackend):
    name = "recording"
    version = "test"

    def __init__(self, calls: list[str], *, fail_on_answer: bool = False):
        self.calls = calls
        self.fail_on_answer = fail_on_answer

    def reset_sample(self, sample_id: str) -> None:
        self.calls.append(f"reset:{sample_id}")

    def ingest_conversation(self, conversation):
        self.calls.append(f"ingest:{conversation.sample_id}")
        return BackendIngestResult(
            ok=True,
            backend_name=self.name,
            sample_id=conversation.sample_id,
            elapsed_ms=1,
        )

    def answer_question(self, question):
        if self.fail_on_answer:
            raise AssertionError("answer should have been loaded from cache")
        self.calls.append(f"answer:{question.question_id}")
        return BackendAnswerResult(
            ok=True,
            backend_name=self.name,
            sample_id=question.sample_id,
            question_id=question.question_id,
            answer=f"answer for {question.question_id}",
            elapsed_ms=1,
        )


class RecordingJudge:
    def __init__(self) -> None:
        self.seen_backend_names: list[str] = []

    def judge(self, *, question, answer):
        self.seen_backend_names.append(answer.backend_name)
        return JudgeResult(ok=True, score=1.0, label="correct", raw={"question_id": question.question_id})


class SkippedBackend(RecordingBackend):
    name = "mem0"
    version = "optional"
    skipped_reason = "not installed"


def _config(tmp_path: Path, **overrides) -> BenchmarkRunConfig:
    values = {
        "dataset_path": str(FIXTURE),
        "backend_names": ["recording"],
        "output_dir": str(tmp_path),
        "answer_model": "fixture-answer",
        "judge_model": "fixture-judge",
        "embedding_model": "fixture-embedding",
        "code_git_commit": "test-commit",
    }
    values.update(overrides)
    return BenchmarkRunConfig(**values)


def _dataset():
    return load_locomo_dataset(FIXTURE)


def test_runner_calls_reset_ingest_answer_in_order(tmp_path: Path) -> None:
    calls: list[str] = []
    report = run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend(calls)],
        config=_config(tmp_path, no_judge=True, judge_model="none", max_questions=2),
    )
    assert report.ok is True
    assert calls == [
        "reset:mini_001",
        "ingest:mini_001",
        "answer:mini_001:q001",
        "answer:mini_001:q002",
    ]


def test_runner_writes_raw_answers_jsonl(tmp_path: Path) -> None:
    run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend([])],
        config=_config(tmp_path, no_judge=True, judge_model="none", max_questions=1),
    )
    raw_path = tmp_path / "raw_answers" / "recording" / "mini_001.jsonl"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["question_id"] == "mini_001:q001"
    assert rows[0]["answer"]["answer"] == "answer for mini_001:q001"


def test_runner_writes_backend_report(tmp_path: Path) -> None:
    run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend([])],
        config=_config(tmp_path, no_judge=True, judge_model="none"),
    )
    report = json.loads((tmp_path / "locomo_recording.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["questions_answered"] == 3
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "comparison_summary.json").exists()
    assert (tmp_path / "comparison_summary.md").exists()


def test_runner_can_resume_from_cache(tmp_path: Path) -> None:
    run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend([])],
        config=_config(tmp_path, no_judge=True, judge_model="none", max_questions=1),
    )
    calls: list[str] = []
    report = run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend(calls, fail_on_answer=True)],
        config=_config(tmp_path, no_judge=True, judge_model="none", max_questions=1, resume=True),
    )
    assert report.backend_reports[0].cached_answers == 1
    assert calls == ["reset:mini_001", "ingest:mini_001"]


def test_runner_does_not_reveal_backend_name_to_judge(tmp_path: Path) -> None:
    judge = RecordingJudge()
    report = run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend([])],
        config=_config(tmp_path, max_questions=1),
        judge=judge,
    )
    assert report.ok is True
    assert judge.seen_backend_names == [""]


def test_runner_caches_judge_outputs(tmp_path: Path) -> None:
    run_locomo_benchmark(
        dataset=_dataset(),
        backends=[RecordingBackend([])],
        config=_config(tmp_path, max_questions=1),
        judge=RecordingJudge(),
    )
    cache = json.loads((tmp_path / "caches" / "runner_cache.json").read_text(encoding="utf-8"))

    assert any(item["kind"] == "judge" for item in cache.values())


def test_runner_marks_optional_backend_skipped_not_failed(tmp_path: Path) -> None:
    report = run_locomo_benchmark(
        dataset=_dataset(),
        backends=[SkippedBackend([])],
        config=_config(tmp_path, backend_names=["mem0"], no_judge=True, judge_model="none"),
    )
    assert report.ok is True
    assert report.backend_reports[0].skipped is True
    assert report.backend_reports[0].skip_reason == "not installed"

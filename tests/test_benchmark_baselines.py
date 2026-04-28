from __future__ import annotations

from pathlib import Path

import pytest

from memco.benchmarks.backends.base import BackendAnswerResult
from memco.benchmarks.backends.embedding_rag import EmbeddingRagBackend
from memco.benchmarks.backends.full_context import FullContextBackend
from memco.benchmarks.backends.sliding_window import SlidingWindowBackend
from memco.benchmarks.backends.summarization import SummarizationBackend
from memco.benchmarks.locomo_loader import load_locomo_dataset
from memco.benchmarks.runner import BenchmarkRunConfig, run_locomo_benchmark


FIXTURE = Path(__file__).parent / "fixtures" / "locomo_mini.json"


def _conversation_and_questions():
    dataset = load_locomo_dataset(FIXTURE)
    return dataset.conversations[0], dataset.questions


def test_full_context_includes_all_sessions() -> None:
    conversation, questions = _conversation_and_questions()
    backend = FullContextBackend()
    backend.reset_sample(conversation.sample_id)
    backend.ingest_conversation(conversation)
    result = backend.answer_question(questions[0])
    context = result.raw["context"]
    assert "[session_01 | 10:00 am on 1 January, 2024]" in context
    assert "[session_02 | 11:00 am on 2 January, 2024]" in context
    assert "Alice: I moved to Lisbon." in context
    assert "Alice: My favorite tool is Python." in context


def test_sliding_window_excludes_old_turns() -> None:
    conversation, questions = _conversation_and_questions()
    backend = SlidingWindowBackend(turns=1)
    backend.reset_sample(conversation.sample_id)
    backend.ingest_conversation(conversation)
    result = backend.answer_question(questions[0])
    context = result.raw["context"]
    assert "My favorite tool is Python." in context
    assert "I moved to Lisbon." not in context


def test_summarization_calls_summarizer_per_session() -> None:
    conversation, questions = _conversation_and_questions()
    calls: list[tuple[str, str]] = []

    def summarizer(previous: str, session: str) -> str:
        calls.append((previous, session))
        return "\n".join(part for part in [previous, session] if part)

    backend = SummarizationBackend(summarizer_fn=summarizer)
    backend.reset_sample(conversation.sample_id)
    ingest = backend.ingest_conversation(conversation)
    result = backend.answer_question(questions[2])
    assert ingest.memory_stats["summary_calls"] == 2
    assert len(calls) == 2
    assert "Rolling summary:" in result.raw["context"]
    assert "My favorite tool is Python." in result.raw["summary"]


def test_embedding_rag_retrieves_top_k_sessions() -> None:
    conversation, questions = _conversation_and_questions()

    def embed(text: str) -> list[float]:
        folded = text.casefold()
        if "favorite tool" in folded or "python" in folded:
            return [1.0, 0.0]
        if "postgres" in folded:
            return [0.0, 1.0]
        return [0.0, 0.0]

    backend = EmbeddingRagBackend(top_k=1, embed_fn=embed)
    backend.reset_sample(conversation.sample_id)
    backend.ingest_conversation(conversation)
    result = backend.answer_question(questions[2])
    assert result.evidence_ids == ["session_02"]
    assert result.retrieved_context[0]["chunk_unit"] == "session"
    assert "My favorite tool is Python." in result.retrieved_context[0]["text"]


def test_embedding_rag_does_not_use_per_turn_default() -> None:
    conversation, questions = _conversation_and_questions()
    backend = EmbeddingRagBackend()
    backend.reset_sample(conversation.sample_id)
    ingest = backend.ingest_conversation(conversation)
    result = backend.answer_question(questions[0])
    assert ingest.memory_stats["chunk_unit"] == "session"
    assert all(item["chunk_unit"] == "session" for item in result.retrieved_context)
    with pytest.raises(ValueError, match="session chunks"):
        EmbeddingRagBackend(chunk_unit="turn")


def test_baselines_emit_token_metrics() -> None:
    conversation, questions = _conversation_and_questions()
    backends = [
        FullContextBackend(),
        SlidingWindowBackend(),
        SummarizationBackend(),
        EmbeddingRagBackend(),
    ]
    for backend in backends:
        backend.reset_sample(conversation.sample_id)
        ingest = backend.ingest_conversation(conversation)
        result = backend.answer_question(questions[0])
        assert isinstance(result, BackendAnswerResult)
        assert result.ok is True
        assert result.backend_name == backend.name
        assert result.tokens["input_tokens"] > 0
        assert result.tokens["output_tokens"] > 0
        assert result.tokens["context_tokens"] > 0
        assert ingest.elapsed_ms >= 0


def test_all_mandatory_baselines_run_on_mini_fixture(tmp_path: Path) -> None:
    dataset = load_locomo_dataset(FIXTURE)
    report = run_locomo_benchmark(
        dataset=dataset,
        backends=[
            FullContextBackend(),
            SlidingWindowBackend(),
            SummarizationBackend(),
            EmbeddingRagBackend(),
        ],
        config=BenchmarkRunConfig(
            dataset_path=str(FIXTURE),
            backend_names=["full_context", "sliding_window", "summarization", "embedding_rag"],
            output_dir=str(tmp_path),
            answer_model="fixture",
            judge_model="none",
            embedding_model="fixture-embedding",
            no_judge=True,
        ),
    )
    assert report.ok is True
    assert {item.backend_name for item in report.backend_reports} == {
        "full_context",
        "sliding_window",
        "summarization",
        "embedding_rag",
    }
    for name in ("full_context", "sliding_window", "summarization", "embedding_rag"):
        assert (tmp_path / f"locomo_{name}.json").exists()

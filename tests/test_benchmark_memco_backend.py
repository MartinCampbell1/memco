from __future__ import annotations

from pathlib import Path

import pytest

from memco.benchmarks.backends.memco_backend import MemcoBenchmarkBackend, locomo_conversation_to_memco_json
from memco.benchmarks.locomo_loader import load_locomo_dataset
from memco.db import get_connection
from memco.services.extraction_service import ExtractionService


FIXTURE = Path(__file__).parent / "fixtures" / "locomo_mini.json"


def _dataset():
    return load_locomo_dataset(FIXTURE)


def _ingest(tmp_path: Path, *, benchmark_mode: bool = True, auto_publish: bool = True) -> tuple[MemcoBenchmarkBackend, object]:
    dataset = _dataset()
    conversation = dataset.conversations[0]
    backend = MemcoBenchmarkBackend(
        benchmark_mode=benchmark_mode,
        auto_publish_safe_candidates=auto_publish,
        runtime_base=tmp_path,
        run_id="test-run",
    )
    backend.reset_sample(conversation.sample_id)
    result = backend.ingest_conversation(conversation)
    assert result.ok is True
    return backend, dataset


def test_memco_backend_creates_two_personas_per_locomo_sample(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path)
    persons = backend._sample_persons[dataset.conversations[0].sample_id]
    assert persons["speaker_a"]["slug"] == "mini-001-speaker-a"
    assert persons["speaker_b"]["slug"] == "mini-001-speaker-b"
    assert persons["speaker_a"]["display_name"] == "Alice"
    assert persons["speaker_b"]["display_name"] == "Bob"


def test_memco_backend_maps_turn_speakers_to_persons(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path)
    settings = backend._sample_settings[dataset.conversations[0].sample_id]
    persons = backend._sample_persons[dataset.conversations[0].sample_id]
    with get_connection(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT speaker_label, speaker_person_id FROM conversation_messages ORDER BY message_index"
        ).fetchall()
    assert [row["speaker_label"] for row in rows] == ["Alice", "Bob", "Alice"]
    assert int(rows[0]["speaker_person_id"]) == int(persons["speaker_a"]["id"])
    assert int(rows[1]["speaker_person_id"]) == int(persons["speaker_b"]["id"])


def test_memco_backend_requires_benchmark_mode_for_auto_publish(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="allowed only in benchmark mode"):
        MemcoBenchmarkBackend(
            benchmark_mode=False,
            auto_publish_safe_candidates=True,
            runtime_base=tmp_path,
        )


def test_memco_backend_does_not_auto_publish_in_private_mode(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path, benchmark_mode=False, auto_publish=False)
    report = backend._sample_report[dataset.conversations[0].sample_id]
    assert report["benchmark_auto_publish_used"] is False
    assert report["manual_review_used"] is False
    assert report["published_facts_count"] == 0
    assert report["pending_candidates_count"] >= 1


def test_memco_backend_answers_target_speaker_only(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path)
    alice_question = dataset.questions[0]
    bob_question = dataset.questions[1]
    alice = backend.answer_question(alice_question)
    bob = backend.answer_question(bob_question)
    assert alice.ok is True
    assert bob.ok is True
    assert alice.raw["target_person_slug"] == "mini-001-speaker-a"
    assert bob.raw["target_person_slug"] == "mini-001-speaker-b"
    assert alice.raw["cross_person_contamination_fact_ids"] == []
    assert bob.raw["cross_person_contamination_fact_ids"] == []


def test_memco_backend_reports_evidence_ids(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path)
    result = backend.answer_question(dataset.questions[0])
    assert result.support_level in {"supported", "partial"}
    assert result.refused is False
    assert result.answer
    assert result.evidence_ids
    assert result.raw["retrieval_latency_ms"] >= 0
    assert result.raw["answer_latency_ms"] >= 0
    assert result.tokens["implemented"] is True


def test_memco_backend_marks_unknown_target_skipped(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path)
    question = dataset.questions[0].model_copy(update={"target_speaker_key": None, "target_speaker_name": None})
    result = backend.answer_question(question)
    assert result.ok is True
    assert result.support_level == "skipped"
    assert result.refused is True
    assert result.raw["skip_reason"] == "target_unknown"


def test_memco_backend_reports_pending_candidates_count(tmp_path: Path) -> None:
    backend, dataset = _ingest(tmp_path)
    report = backend._sample_report[dataset.conversations[0].sample_id]
    assert report["manual_review_used"] is False
    assert report["benchmark_auto_publish_used"] is True
    assert report["pending_candidates_count"] >= 0
    assert report["published_facts_count"] >= 1


def test_memco_backend_passes_live_smoke_chunk_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_extract_candidates(self, conn, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(ExtractionService, "extract_candidates_from_conversation", fake_extract_candidates)
    dataset = _dataset()
    conversation = dataset.conversations[0]
    backend = MemcoBenchmarkBackend(
        benchmark_mode=True,
        runtime_base=tmp_path,
        run_id="test-run",
        max_ingest_chunks=2,
    )
    backend.reset_sample(conversation.sample_id)
    result = backend.ingest_conversation(conversation)

    assert result.ok is True
    assert captured["max_chunks"] == 2
    assert result.memory_stats["max_ingest_chunks"] == 2


def test_locomo_conversation_to_memco_json_shape() -> None:
    conversation = _dataset().conversations[0]
    payload = locomo_conversation_to_memco_json(conversation)
    assert payload["sample_id"] == "mini_001"
    assert payload["speaker_a"] == "Alice"
    assert payload["speaker_b"] == "Bob"
    assert payload["messages"][0]["session_id"] == "session_1"
    assert payload["messages"][0]["speaker_key"] == "speaker_a"

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memco.benchmarks.locomo_loader import LoCoMoLoaderError, load_locomo_dataset


OFFICIAL_LOCOMO = Path("external/locomo/data/locomo10.json")
MINI_LOCOMO = Path("tests/fixtures/locomo_mini.json")


def _official_or_skip() -> Path:
    if not OFFICIAL_LOCOMO.exists():
        pytest.skip("official LoCoMo dataset is not checked out")
    return OFFICIAL_LOCOMO


def test_locomo_loader_reads_official_file():
    dataset = load_locomo_dataset(_official_or_skip())

    assert dataset.source_path.endswith("external/locomo/data/locomo10.json")
    assert len(dataset.dataset_sha256) == 64
    assert dataset.conversations
    assert dataset.questions


def test_locomo_loader_extracts_10_conversations():
    dataset = load_locomo_dataset(_official_or_skip())

    assert len(dataset.conversations) == 10


def test_locomo_loader_extracts_turns_with_session_dates():
    dataset = load_locomo_dataset(MINI_LOCOMO)
    conversation = dataset.conversations[0]

    assert conversation.turns[0].session_id == "session_1"
    assert conversation.turns[0].session_index == 1
    assert conversation.turns[0].session_datetime == "10:00 am on 1 January, 2024"
    assert conversation.turns[0].speaker_key == "speaker_a"
    assert conversation.turns[1].speaker_key == "speaker_b"
    assert conversation.turns[0].dia_id == "D1:1"


def test_locomo_loader_extracts_questions():
    dataset = load_locomo_dataset(MINI_LOCOMO)

    assert len(dataset.questions) == 3
    assert all(question.question_id for question in dataset.questions)
    assert all(question.sample_id == "mini_001" for question in dataset.questions)
    assert all(question.question for question in dataset.questions)
    assert all(question.gold_answer for question in dataset.questions)
    assert dataset.questions[0].evidence == [{"ref": "D1:1"}]


def test_locomo_loader_resolves_target_when_name_present():
    dataset = load_locomo_dataset(MINI_LOCOMO)
    by_question = {question.question: question for question in dataset.questions}

    assert by_question["Where did Alice move?"].target_speaker_key == "speaker_a"
    assert by_question["Where did Alice move?"].target_speaker_name == "Alice"
    assert by_question["What database did Bob start using?"].target_speaker_key == "speaker_b"
    assert by_question["What is my favorite tool?"].target_speaker_key is None
    assert dataset.unknown_target_count == 1


def test_locomo_loader_fails_when_no_questions(tmp_path):
    path = tmp_path / "no-questions.json"
    payload = json.loads(MINI_LOCOMO.read_text(encoding="utf-8"))
    payload[0].pop("qa")
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LoCoMoLoaderError, match="no QA annotations found"):
        load_locomo_dataset(path)


def test_locomo_loader_dataset_sha_is_stable():
    first = load_locomo_dataset(MINI_LOCOMO)
    second = load_locomo_dataset(MINI_LOCOMO)

    assert first.dataset_sha256 == second.dataset_sha256


def test_locomo_loader_official_questions_have_required_fields():
    dataset = load_locomo_dataset(_official_or_skip())

    assert len(dataset.questions) > 0
    assert all(question.question_id for question in dataset.questions)
    assert all(question.sample_id for question in dataset.questions)
    assert all(question.question for question in dataset.questions)
    assert all(question.gold_answer for question in dataset.questions)
    assert dataset.unknown_target_count >= 0
    assert any("QA annotations read from field qa" in warning for warning in dataset.loader_warnings)

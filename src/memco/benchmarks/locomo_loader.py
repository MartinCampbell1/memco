from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from memco.benchmarks.models import LoCoMoDataset, NormalizedConversation, NormalizedQuestion, NormalizedTurn


SESSION_RE = re.compile(r"^session_(\d+)$")
FIRST_PERSON_RE = re.compile(r"\b(?:i|me|my|mine|myself|we|our|ours)\b", re.IGNORECASE)
EXPLICIT_TARGET_FIELDS = ("target_speaker", "target", "speaker", "user", "answerer")
QA_FIELDS = ("qa", "qas", "questions", "question_answering", "qa_pairs")


class LoCoMoLoaderError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoCoMoLoaderError(f"LoCoMo loader error: invalid JSON: {exc}") from exc


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    if isinstance(payload, dict):
        for key in ("samples", "data", "conversations"):
            value = payload.get(key)
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value
    raise LoCoMoLoaderError("LoCoMo loader error: expected a list of conversation samples.")


def _speaker_key(name: str, *, speaker_a: str, speaker_b: str) -> str:
    normalized = name.strip().casefold()
    if normalized == speaker_a.strip().casefold():
        return "speaker_a"
    if normalized == speaker_b.strip().casefold():
        return "speaker_b"
    return name.strip() or "unknown"


def _session_items(conversation: dict[str, Any]) -> list[tuple[int, str, list[dict[str, Any]]]]:
    sessions: list[tuple[int, str, list[dict[str, Any]]]] = []
    for key, value in conversation.items():
        match = SESSION_RE.match(key)
        if not match or not isinstance(value, list):
            continue
        session_index = int(match.group(1))
        turns = [item for item in value if isinstance(item, dict)]
        sessions.append((session_index, key, turns))
    return sorted(sessions, key=lambda item: item[0])


def _normalize_conversation(sample: dict[str, Any], *, warnings: list[str]) -> NormalizedConversation:
    sample_id = str(sample.get("sample_id") or "")
    if not sample_id:
        raise LoCoMoLoaderError("LoCoMo loader error: sample is missing sample_id.")
    conversation = sample.get("conversation")
    if not isinstance(conversation, dict):
        raise LoCoMoLoaderError(f"LoCoMo loader error: sample {sample_id} is missing conversation.")
    speaker_a = str(conversation.get("speaker_a") or sample.get("speaker_a") or "").strip()
    speaker_b = str(conversation.get("speaker_b") or sample.get("speaker_b") or "").strip()
    if not speaker_a or not speaker_b:
        raise LoCoMoLoaderError(f"LoCoMo loader error: sample {sample_id} is missing speaker_a/speaker_b.")

    turns: list[NormalizedTurn] = []
    for session_index, session_id, session_turns in _session_items(conversation):
        session_datetime = conversation.get(f"{session_id}_date_time")
        for raw_turn in session_turns:
            speaker_name = str(raw_turn.get("speaker") or "").strip()
            text = str(raw_turn.get("text") or "").strip()
            if not speaker_name or not text:
                warnings.append(f"{sample_id}:{session_id}: skipped turn missing speaker/text")
                continue
            turns.append(
                NormalizedTurn(
                    sample_id=sample_id,
                    session_id=session_id,
                    session_index=session_index,
                    session_datetime=str(session_datetime) if session_datetime else None,
                    dia_id=raw_turn.get("dia_id"),
                    speaker_key=_speaker_key(speaker_name, speaker_a=speaker_a, speaker_b=speaker_b),
                    speaker_name=speaker_name,
                    text=text,
                    raw=raw_turn,
                )
            )
    if not turns:
        raise LoCoMoLoaderError(f"LoCoMo loader error: sample {sample_id} has no dialog turns.")
    return NormalizedConversation(
        sample_id=sample_id,
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        turns=turns,
        raw=sample,
    )


def _qa_items(sample: dict[str, Any], *, sample_id: str, warnings: list[str]) -> list[dict[str, Any]]:
    for field in QA_FIELDS:
        value = sample.get(field)
        if isinstance(value, list):
            warnings.append(f"{sample_id}: QA annotations read from field {field}")
            return [item for item in value if isinstance(item, dict)]
    return []


def _target_from_value(value: Any, *, speaker_a: str, speaker_b: str) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    lowered = text.casefold()
    if lowered in {"speaker_a", "a"} or lowered == speaker_a.casefold():
        return "speaker_a", speaker_a
    if lowered in {"speaker_b", "b"} or lowered == speaker_b.casefold():
        return "speaker_b", speaker_b
    return None, None


def _resolve_target(
    qa: dict[str, Any],
    *,
    question: str,
    speaker_a: str,
    speaker_b: str,
    sample_id: str,
    question_id: str,
    warnings: list[str],
) -> tuple[str | None, str | None, str]:
    for field in EXPLICIT_TARGET_FIELDS:
        if field in qa:
            key, name = _target_from_value(qa.get(field), speaker_a=speaker_a, speaker_b=speaker_b)
            warnings.append(f"{sample_id}:{question_id}: target heuristic explicit_field:{field}")
            if key:
                return key, name, f"explicit_field:{field}"
    matches: list[tuple[str, str]] = []
    question_folded = question.casefold()
    if speaker_a.casefold() in question_folded:
        matches.append(("speaker_a", speaker_a))
    if speaker_b.casefold() in question_folded:
        matches.append(("speaker_b", speaker_b))
    if len(matches) == 1:
        warnings.append(f"{sample_id}:{question_id}: target heuristic speaker_name_match")
        return matches[0][0], matches[0][1], "speaker_name_match"
    if FIRST_PERSON_RE.search(question):
        warnings.append(f"{sample_id}:{question_id}: target unknown first_person_question")
        return None, None, "unknown"
    warnings.append(f"{sample_id}:{question_id}: target unknown no_unique_signal")
    return None, None, "unknown"


def _normalize_questions(
    sample: dict[str, Any],
    *,
    speaker_a: str,
    speaker_b: str,
    warnings: list[str],
) -> list[NormalizedQuestion]:
    sample_id = str(sample.get("sample_id") or "")
    questions: list[NormalizedQuestion] = []
    for index, qa in enumerate(_qa_items(sample, sample_id=sample_id, warnings=warnings), start=1):
        question = str(qa.get("question") or qa.get("query") or "").strip()
        answer = qa.get("answer", qa.get("gold_answer", ""))
        if not question or answer in {None, ""}:
            warnings.append(f"{sample_id}: skipped QA item {index} missing question/answer")
            continue
        question_id = str(qa.get("question_id") or qa.get("id") or f"{sample_id}:q{index:03d}")
        target_key, target_name, target_resolution = _resolve_target(
            qa,
            question=question,
            speaker_a=speaker_a,
            speaker_b=speaker_b,
            sample_id=sample_id,
            question_id=question_id,
            warnings=warnings,
        )
        evidence = qa.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = [evidence]
        questions.append(
            NormalizedQuestion(
                question_id=question_id,
                sample_id=sample_id,
                question=question,
                gold_answer=str(answer),
                category=str(qa.get("category")) if qa.get("category") is not None else None,
                target_speaker_key=target_key,
                target_speaker_name=target_name,
                target_resolution=target_resolution,
                evidence=[{"ref": item} for item in evidence],
                raw=qa,
            )
        )
    return questions


def load_locomo_dataset(path: str | Path) -> LoCoMoDataset:
    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        raise LoCoMoLoaderError(f"LoCoMo loader error: dataset not found: {source_path}")
    warnings: list[str] = []
    conversations: list[NormalizedConversation] = []
    questions: list[NormalizedQuestion] = []
    for sample in _records(_load_json(source_path)):
        conversation = _normalize_conversation(sample, warnings=warnings)
        conversations.append(conversation)
        questions.extend(
            _normalize_questions(
                sample,
                speaker_a=conversation.speaker_a,
                speaker_b=conversation.speaker_b,
                warnings=warnings,
            )
        )
    if not questions:
        raise LoCoMoLoaderError("LoCoMo loader error: no QA annotations found. Inspect dataset schema.")
    unknown_target_count = sum(1 for question in questions if question.target_speaker_key is None)
    return LoCoMoDataset(
        source_path=str(source_path),
        dataset_sha256=_sha256(source_path),
        conversations=conversations,
        questions=questions,
        unknown_target_count=unknown_target_count,
        loader_warnings=warnings,
    )

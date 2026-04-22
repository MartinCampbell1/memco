from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from memco.utils import slugify


EXTRACTION_SCHEMA_NAME = "memory_fact_candidates"


@dataclass(frozen=True)
class ExtractionContext:
    text: str
    subject_key: str
    subject_display: str
    speaker_label: str
    person_id: int | None
    conn: Any = None
    workspace_id: int | None = None
    message_id: int | None = None
    source_segment_id: int | None = None
    session_id: int | None = None
    occurred_at: str = ""
    resolve_person_id: Callable[[str], int | None] | None = None


def build_extraction_system_prompt(*, include_style: bool, include_psychometrics: bool) -> str:
    return (
        "Extract persona-memory candidates as strict JSON. "
        "Return a JSON array. "
        f"include_style={str(include_style).lower()} "
        f"include_psychometrics={str(include_psychometrics).lower()}."
    )


def build_prompt_payload(
    context: ExtractionContext,
    *,
    include_style: bool,
    include_psychometrics: bool,
) -> dict[str, Any]:
    return {
        "text": context.text,
        "subject_key": context.subject_key,
        "subject_display": context.subject_display,
        "speaker_label": context.speaker_label,
        "person_id": context.person_id,
        "message_id": context.message_id,
        "source_segment_id": context.source_segment_id,
        "session_id": context.session_id,
        "occurred_at": context.occurred_at,
        "include_style": include_style,
        "include_psychometrics": include_psychometrics,
    }


def clean_value(value: str) -> str:
    cleaned = value.strip().strip(".,!?;:").strip()
    return " ".join(cleaned.split())


def subject_key(person_id: int | None, speaker_label: str, person_hint: str | None = None) -> str:
    if person_id is not None:
        return f"p{person_id}"
    fallback = speaker_label or person_hint or "unknown"
    return slugify(fallback)


def display_subject(speaker_label: str, person_id: int | None) -> str:
    if speaker_label:
        return speaker_label
    if person_id is not None:
        return f"Person {person_id}"
    return "Unknown speaker"


def review_reasons_for_context(context: ExtractionContext) -> list[str]:
    if context.person_id is None:
        return ["speaker_unresolved"]
    return []


def build_evidence(context: ExtractionContext) -> list[dict[str, Any]]:
    return [
        {
            "quote": context.text.strip(),
            "message_ids": [str(context.message_id)] if context.message_id is not None else [],
            "source_segment_ids": [int(context.source_segment_id)] if context.source_segment_id is not None else [],
            "session_ids": [int(context.session_id)] if context.session_id is not None else [],
            "chunk_kind": "conversation",
        }
    ]


REQUIRED_CANDIDATE_KEYS = {
    "domain",
    "category",
    "subcategory",
    "canonical_key",
    "payload",
    "summary",
    "confidence",
    "reason",
    "needs_review",
    "evidence",
}


def _require_string(payload: dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"payload.{key} must be a non-empty string")


def _require_bool(payload: dict[str, Any], key: str) -> None:
    if not isinstance(payload.get(key), bool):
        raise ValueError(f"payload.{key} must be a bool")


def _require_list_of_strings(payload: dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"payload.{key} must be a list of non-empty strings")


def validate_candidate_payload(*, domain: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("candidate payload must be a dict")

    if domain == "biography":
        if category == "residence":
            _require_string(payload, "city")
        elif category == "origin":
            _require_string(payload, "place")
        elif category == "identity":
            _require_string(payload, "name")
        elif category == "education":
            _require_string(payload, "institution")
            _require_string(payload, "field")
        elif category == "family":
            _require_string(payload, "relation")
            _require_string(payload, "name")
        elif category == "pets":
            _require_string(payload, "pet_type")
            _require_string(payload, "pet_name")
        elif category == "languages":
            _require_list_of_strings(payload, "languages")
        elif category == "habits":
            _require_string(payload, "habit")
        elif category == "goals":
            _require_string(payload, "goal")
        elif category == "constraints":
            _require_string(payload, "constraint")
        else:
            raise ValueError(f"unsupported biography category: {category}")
        return payload

    if domain == "preferences":
        if category != "preference":
            raise ValueError(f"unsupported preferences category: {category}")
        _require_string(payload, "value")
        if "polarity" in payload:
            _require_string(payload, "polarity")
        if "strength" in payload:
            _require_string(payload, "strength")
        if "reason" in payload and not isinstance(payload.get("reason"), str):
            raise ValueError("payload.reason must be a string")
        if "is_current" in payload:
            _require_bool(payload, "is_current")
        return payload

    if domain == "social_circle":
        if category == "relationship_event":
            _require_string(payload, "target_label")
            _require_string(payload, "event")
            if "context" in payload and not isinstance(payload.get("context", ""), str):
                raise ValueError("payload.context must be a string")
            return payload
        _require_string(payload, "relation")
        _require_string(payload, "target_label")
        if payload.get("target_person_id") is not None and not isinstance(payload.get("target_person_id"), int):
            raise ValueError("payload.target_person_id must be an int or null")
        if "is_current" in payload:
            _require_bool(payload, "is_current")
        return payload

    if domain == "work":
        if category == "employment":
            _require_string(payload, "title")
            if "is_current" in payload:
                _require_bool(payload, "is_current")
        elif category == "role":
            _require_string(payload, "role")
            if "is_current" in payload:
                _require_bool(payload, "is_current")
        elif category == "org":
            _require_string(payload, "org")
            if "is_current" in payload:
                _require_bool(payload, "is_current")
        elif category == "project":
            _require_string(payload, "project")
        elif category == "skill":
            _require_string(payload, "skill")
        elif category == "tool":
            _require_string(payload, "tool")
        else:
            raise ValueError(f"unsupported work category: {category}")
        return payload

    if domain == "experiences":
        if category != "event":
            raise ValueError(f"unsupported experiences category: {category}")
        _require_string(payload, "event")
        if "summary" in payload:
            _require_string(payload, "summary")
        if "participants" in payload:
            _require_list_of_strings(payload, "participants")
        if "event_at" in payload and not isinstance(payload.get("event_at", ""), str):
            raise ValueError("payload.event_at must be a string")
        if "temporal_anchor" in payload and not isinstance(payload.get("temporal_anchor", ""), str):
            raise ValueError("payload.temporal_anchor must be a string")
        if "outcome" in payload and not isinstance(payload.get("outcome", ""), str):
            raise ValueError("payload.outcome must be a string")
        if "valence" in payload:
            _require_string(payload, "valence")
        return payload

    if domain == "psychometrics":
        _require_string(payload, "framework")
        _require_string(payload, "trait")
        if not isinstance(payload.get("score"), (int, float)):
            raise ValueError("payload.score must be numeric")
        _require_string(payload, "score_scale")
        _require_string(payload, "direction")
        if not isinstance(payload.get("confidence"), (int, float)):
            raise ValueError("payload.confidence must be numeric")
        evidence_quotes = payload.get("evidence_quotes")
        if not isinstance(evidence_quotes, list) or not evidence_quotes:
            raise ValueError("payload.evidence_quotes must be a non-empty list")
        counterevidence_quotes = payload.get("counterevidence_quotes")
        if not isinstance(counterevidence_quotes, list):
            raise ValueError("payload.counterevidence_quotes must be a list")
        _require_bool(payload, "conservative_update")
        _require_bool(payload, "use_in_generation")
        _require_string(payload, "safety_notes")
        return payload

    if domain == "style":
        _require_string(payload, "tone")
        _require_string(payload, "generation_guidance")
        return payload

    raise ValueError(f"unsupported candidate domain: {domain}")


def validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_CANDIDATE_KEYS.difference(candidate)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"candidate is missing required keys: {missing_list}")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("candidate evidence must be a list")
    validate_candidate_payload(
        domain=str(candidate["domain"]),
        category=str(candidate["category"]),
        payload=candidate.get("payload") or {},
    )
    return candidate

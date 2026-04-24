from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from memco.utils import slugify


EXTRACTION_SCHEMA_NAME = "memory_fact_candidates"
EXTRACTION_CONTRACT_VERSION = "v2_llm_first"


@dataclass(frozen=True)
class DomainPromptContract:
    domain: str
    instructions: tuple[str, ...]
    categories: dict[str, tuple[str, ...]]
    ambiguity_rules: tuple[str, ...]
    evidence_rules: tuple[str, ...]
    temporal_rules: tuple[str, ...]
    negation_rules: tuple[str, ...]
    examples: tuple[dict[str, str], ...] = ()


DOMAIN_PROMPT_CONTRACTS: dict[str, DomainPromptContract] = {
    "biography": DomainPromptContract(
        domain="biography",
        instructions=(
            "Extract stable biographical facts only when the subject describes them directly or with a strong paraphrase.",
            "Use needs_review=true when the speaker is unresolved or the statement is materially ambiguous.",
        ),
        categories={
            "residence": ("city",),
            "origin": ("place",),
            "identity": ("name",),
            "education": ("institution", "field"),
            "family": ("relation", "name"),
            "pets": ("pet_type", "pet_name"),
            "age_birth": ("age", "birth_date", "birth_year"),
            "health": ("health_fact", "status"),
            "languages": ("languages",),
            "habits": ("habit",),
            "goals": ("goal",),
            "constraints": ("constraint",),
            "values": ("value", "context"),
            "finances": ("financial_note", "caution"),
            "legal": ("legal_note", "caution"),
            "travel_history": ("location", "event_at", "date_range"),
            "life_milestone": ("milestone", "event_at"),
            "communication_preference": ("preference", "language", "context"),
            "other_stable_self_knowledge": ("fact", "context"),
        },
        ambiguity_rules=(
            "Do not turn tentative relocation plans into current residence facts.",
            "Indirect phrasing like 'Lisbon is my base' is allowed only when it clearly describes the current state.",
        ),
        evidence_rules=(
            "Every item must carry direct quote evidence from the source snippet.",
        ),
        temporal_rules=(
            "Prefer current-state biography facts unless the snippet explicitly marks them as past.",
            "When timing is uncertain, keep the fact out instead of inventing a current state.",
        ),
        negation_rules=(
            "Negated constraints can be extracted only as constraints, never as positive preferences or residences.",
        ),
        examples=(
            {
                "text": "I was born in 1990 and I speak English and Spanish.",
                "extract": "age_birth.birth_year=1990; languages.languages=[English, Spanish]",
            },
            {
                "text": "I might move to Paris next year.",
                "extract": "no current residence fact",
            },
            {
                "text": "Please send me short direct updates in English.",
                "extract": "communication_preference.preference=short direct updates; language=English",
            },
        ),
    ),
    "preferences": DomainPromptContract(
        domain="preferences",
        instructions=(
            "Extract likes, dislikes, and preferences with polarity and current-vs-past handling.",
            "Indirect preference phrasing is allowed when the favorite/go-to choice is explicit.",
        ),
        categories={
            "preference": (
                "value",
                "preference_domain",
                "preference_category",
                "polarity",
                "strength",
                "is_current",
                "valid_from",
                "valid_to",
                "original_phrasing",
                "reason",
                "context",
            )
        },
        ambiguity_rules=(
            "Keep hypothetical or uncertain tastes out of the result set.",
            "Self-corrections should prefer the current statement over the superseded one.",
        ),
        evidence_rules=(
            "Quote the exact preference statement or the closest supporting clause.",
        ),
        temporal_rules=(
            "Use is_current=false for 'used to' preferences or clearly past tastes.",
        ),
        negation_rules=(
            "A negated statement like 'I do not like sushi' must never become a positive preference.",
        ),
        examples=(
            {
                "text": "I used to prefer tea, but now I prefer coffee.",
                "extract": "preference.value=tea; polarity=like; is_current=false; valid_to=now; preference_category=drink; preference.value=coffee; is_current=true",
            },
            {
                "text": "I strongly dislike coffee because it makes me anxious.",
                "extract": "preference.value=coffee; polarity=dislike; strength=strong; reason=it makes me anxious",
            },
            {
                "text": "If I prefer tea later, I will tell you.",
                "extract": "no preference fact",
            },
        ),
    ),
    "social_circle": DomainPromptContract(
        domain="social_circle",
        instructions=(
            "Extract social relations and relationship events only when the subject names the relation or event.",
            "If the target person cannot be resolved, keep the candidate but mark it needs_review.",
        ),
        categories={
            "relationship_event": ("target_label", "target_person_id", "event", "context"),
            "friend": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "brother": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "sister": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "wife": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "husband": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "partner": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "spouse": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "mother": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "father": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "son": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "daughter": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "colleague": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "boss": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "manager": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "roommate": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
            "neighbor": ("relation", "target_label", "target_person_id", "is_current", "closeness", "trust", "valence", "aliases", "is_private"),
        },
        ambiguity_rules=(
            "Do not infer a relationship from weak co-occurrence or event-only evidence.",
        ),
        evidence_rules=(
            "Relation claims need quote evidence naming both the target and relation/event.",
        ),
        temporal_rules=(
            "Use is_current=false only when the snippet explicitly marks the relation as past.",
        ),
        negation_rules=(
            "Do not invert negated relation claims into positive relations.",
        ),
    ),
    "work": DomainPromptContract(
        domain="work",
        instructions=(
            "Extract employment, org, role, project, tool, and skill facts from direct or strong indirect phrasing.",
            "Current-vs-past work state must be preserved.",
        ),
        categories={
            "employment": ("title", "role", "org", "client", "status", "is_current", "start_date", "end_date", "team", "constraints", "preferences"),
            "engagement": ("engagement", "role", "org", "client", "status", "start_date", "end_date", "outcomes", "team"),
            "role": ("role", "is_current", "status", "start_date", "end_date"),
            "org": ("org", "client", "is_current", "status"),
            "project": ("project", "role", "org", "client", "outcomes", "status", "start_date", "end_date", "team"),
            "skill": ("skill",),
            "tool": ("tool",),
        },
        ambiguity_rules=(
            "Do not turn plans, interviews, or aspirations into current employment.",
        ),
        evidence_rules=(
            "Work items must quote the relevant clause that names the role, org, tool, skill, or project.",
        ),
        temporal_rules=(
            "Use is_current=false for past employment or org history when the snippet says 'used to' or equivalent.",
        ),
        negation_rules=(
            "Negated capability statements should not become positive skills or tools.",
        ),
        examples=(
            {
                "text": "I work as a staff engineer at OpenAI with the Applied team since 2022.",
                "extract": "employment.title=staff engineer; org=OpenAI; team=Applied; status=current; start_date=2022",
            },
            {
                "text": "I consult for Acme as a platform advisor since 2024.",
                "extract": "engagement=consulting; client=Acme; role=platform advisor; start_date=2024",
            },
            {
                "text": "I shipped Project Atlas for Acme with the mobile team. The outcome was 20% faster onboarding.",
                "extract": "project=Project Atlas; client=Acme; team=mobile; status=completed; outcomes=[20% faster onboarding]",
            },
        ),
    ),
    "experiences": DomainPromptContract(
        domain="experiences",
        instructions=(
            "Extract lived events with summary, participants, outcome, and temporal cues when stated.",
            "Use event_at only for explicit event dates; use temporal_anchor for approximate or relative timing.",
        ),
        categories={
            "event": (
                "event",
                "summary",
                "event_at",
                "date_range",
                "location",
                "participants",
                "valence",
                "intensity",
                "outcome",
                "lesson",
                "recurrence",
                "linked_persons",
                "linked_projects",
                "event_hierarchy",
                "temporal_anchor",
            )
        },
        ambiguity_rules=(
            "Keep approximate timing separate from exact event dates.",
        ),
        evidence_rules=(
            "Experience items must include quote evidence for the event description.",
        ),
        temporal_rules=(
            "Do not promote observed narration time into event_at.",
            "If timing is approximate, leave event_at empty and store the phrase in temporal_anchor.",
        ),
        negation_rules=(
            "Do not extract events that are explicitly denied or described as not having happened.",
        ),
        examples=(
            {
                "text": "In March 2024, I attended launch week with Bob and Dana during Project Phoenix. We won the beta award and I learned to plan rehearsals.",
                "extract": "event=launch week; linked_persons=[Bob,Dana]; linked_projects=[Project Phoenix]; outcome=won the beta award; lesson=plan rehearsals",
            },
            {
                "text": "Every summer I went to PyCon with Bob from 2021 to 2023.",
                "extract": "event=PyCon; recurrence=every summer; date_range=2021 to 2023; linked_persons=[Bob]",
            },
        ),
    ),
    "psychometrics": DomainPromptContract(
        domain="psychometrics",
        instructions=(
            "Extract conservative psychometric signals only as non-diagnostic hints.",
            "Psychometrics must remain separate from factual truth and require evidence plus counterevidence handling.",
        ),
        categories={
            "trait": (
                "framework",
                "trait",
                "score",
                "score_scale",
                "direction",
                "confidence",
                "evidence_quotes",
                "counterevidence_quotes",
                "conservative_update",
                "use_in_generation",
                "safety_notes",
            ),
        },
        ambiguity_rules=(
            "Weak or conflicting signals should stay conservative and may set use_in_generation=false.",
        ),
        evidence_rules=(
            "Every psychometric hint needs evidence_quotes and may include counterevidence_quotes.",
        ),
        temporal_rules=(
            "Psychometric last_updated can reflect when the signal was observed, not when a trait became true.",
        ),
        negation_rules=(
            "Do not infer a high-trait signal from explicit negation of that trait.",
        ),
    ),
    "style": DomainPromptContract(
        domain="style",
        instructions=(
            "Extract communication style only when explicitly requested via include_style=true.",
        ),
        categories={"communication_style": ("tone", "generation_guidance")},
        ambiguity_rules=("Leave style out when the tone is unclear.",),
        evidence_rules=("Style must still quote the supporting snippet.",),
        temporal_rules=("Treat style as an observed communication hint, not a permanent trait.",),
        negation_rules=("Do not infer a tone from explicit denial of that tone.",),
    ),
}


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


def build_extraction_system_prompt(
    *,
    include_style: bool,
    include_psychometrics: bool,
    domain_names: tuple[str, ...] | None = None,
) -> str:
    contract_payload = build_extraction_contract(
        include_style=include_style,
        include_psychometrics=include_psychometrics,
        domain_names=domain_names,
    )
    return (
        "You are the Memco extraction runtime. "
        "The live runtime path is LLM-first structured extraction. "
        "Rule-based extraction is fallback-only for fixture/test or emergency use. "
        "Return strict json only. "
        "Use the contract below exactly. "
        "Never return prose outside json. "
        f"include_style={str(include_style).lower()} "
        f"include_psychometrics={str(include_psychometrics).lower()}.\n"
        f"{json.dumps(contract_payload, ensure_ascii=False, sort_keys=True)}"
    )


def _selected_domain_contracts(
    *,
    include_style: bool,
    include_psychometrics: bool,
    domain_names: tuple[str, ...] | None = None,
) -> list[DomainPromptContract]:
    selected = [
        DOMAIN_PROMPT_CONTRACTS["biography"],
        DOMAIN_PROMPT_CONTRACTS["preferences"],
        DOMAIN_PROMPT_CONTRACTS["social_circle"],
        DOMAIN_PROMPT_CONTRACTS["work"],
        DOMAIN_PROMPT_CONTRACTS["experiences"],
    ]
    if include_psychometrics:
        selected.append(DOMAIN_PROMPT_CONTRACTS["psychometrics"])
    if include_style:
        selected.append(DOMAIN_PROMPT_CONTRACTS["style"])
    if domain_names is not None:
        allowed = set(domain_names)
        selected = [contract for contract in selected if contract.domain in allowed]
    return selected


def build_extraction_contract(
    *,
    include_style: bool,
    include_psychometrics: bool,
    domain_names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    domains = []
    for contract in _selected_domain_contracts(
        include_style=include_style,
        include_psychometrics=include_psychometrics,
        domain_names=domain_names,
    ):
        domains.append(
            {
                "domain": contract.domain,
                "instructions": list(contract.instructions),
                "categories": {key: list(value) for key, value in contract.categories.items()},
                "ambiguity_rules": list(contract.ambiguity_rules),
                "evidence_rules": list(contract.evidence_rules),
                "temporal_rules": list(contract.temporal_rules),
                "negation_rules": list(contract.negation_rules),
                "examples": list(contract.examples),
            }
        )
    return {
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "mode": "llm_first_structured_extraction",
        "fallback_mode": "rule_based_fixture_only",
        "top_level_output": {
            "type": "object",
            "required_keys": ["items"],
            "items_value_type": "array",
        },
        "candidate_required_keys": sorted(REQUIRED_CANDIDATE_KEYS),
        "global_rules": [
            "Only extract facts grounded in the supplied snippet.",
            "Never convert negation, uncertainty, or hypotheticals into current positive facts.",
            "Every candidate must carry direct quote evidence.",
            "When ambiguity is material but still worth surfacing, set needs_review=true and explain in reason.",
        ],
        "domains": domains,
    }


def build_prompt_payload(
    context: ExtractionContext,
    *,
    include_style: bool,
    include_psychometrics: bool,
    domain_names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "extraction_mode": "llm_first_structured_extraction",
        "json_output_required": True,
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
        "output_contract": build_extraction_contract(
            include_style=include_style,
            include_psychometrics=include_psychometrics,
            domain_names=domain_names,
        ),
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


def _require_any_string(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    if not any(isinstance(payload.get(key), str) and payload.get(key).strip() for key in keys):
        joined = ", ".join(f"payload.{key}" for key in keys)
        raise ValueError(f"one of {joined} must be a non-empty string")


def _optional_string(payload: dict[str, Any], key: str) -> None:
    if key in payload and not isinstance(payload.get(key), str):
        raise ValueError(f"payload.{key} must be a string")


def _optional_number(payload: dict[str, Any], key: str) -> None:
    if key in payload and not isinstance(payload.get(key), (int, float)):
        raise ValueError(f"payload.{key} must be numeric")


def _optional_list_of_strings(payload: dict[str, Any], key: str) -> None:
    if key in payload:
        _require_list_of_strings(payload, key)


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
        elif category == "age_birth":
            _require_any_string(payload, ("age", "birth_date", "birth_year"))
        elif category == "health":
            _require_string(payload, "health_fact")
        elif category == "languages":
            _require_list_of_strings(payload, "languages")
        elif category == "habits":
            _require_string(payload, "habit")
        elif category == "goals":
            _require_string(payload, "goal")
        elif category == "constraints":
            _require_string(payload, "constraint")
        elif category == "values":
            _require_string(payload, "value")
        elif category == "finances":
            _require_string(payload, "financial_note")
            _optional_string(payload, "caution")
        elif category == "legal":
            _require_string(payload, "legal_note")
            _optional_string(payload, "caution")
        elif category == "travel_history":
            _require_string(payload, "location")
            _optional_string(payload, "event_at")
            _optional_string(payload, "date_range")
        elif category == "life_milestone":
            _require_string(payload, "milestone")
            _optional_string(payload, "event_at")
        elif category == "communication_preference":
            _require_string(payload, "preference")
            _optional_string(payload, "language")
            _optional_string(payload, "context")
        elif category == "other_stable_self_knowledge":
            _require_string(payload, "fact")
            _optional_string(payload, "context")
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
        for key in ("preference_domain", "preference_category", "valid_from", "valid_to", "original_phrasing", "context"):
            _optional_string(payload, key)
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
            for key in ("valence", "sensitivity", "related_person_name", "relation_type"):
                _optional_string(payload, key)
            for key in ("closeness", "trust"):
                _optional_number(payload, key)
            _optional_list_of_strings(payload, "aliases")
            if "is_private" in payload:
                _require_bool(payload, "is_private")
            return payload
        _require_string(payload, "relation")
        _require_string(payload, "target_label")
        if payload.get("target_person_id") is not None and not isinstance(payload.get("target_person_id"), int):
            raise ValueError("payload.target_person_id must be an int or null")
        if "is_current" in payload:
            _require_bool(payload, "is_current")
        for key in ("closeness", "trust"):
            _optional_number(payload, key)
        for key in ("valence", "sensitivity", "relation_type", "related_person_name"):
            _optional_string(payload, key)
        _optional_list_of_strings(payload, "aliases")
        if "is_private" in payload:
            _require_bool(payload, "is_private")
        return payload

    if domain == "work":
        if category == "employment":
            _require_string(payload, "title")
            if "is_current" in payload:
                _require_bool(payload, "is_current")
            for key in ("role", "org", "client", "status", "start_date", "end_date", "team", "constraints", "preferences"):
                _optional_string(payload, key)
        elif category == "engagement":
            _require_string(payload, "engagement")
            for key in ("role", "org", "client", "status", "start_date", "end_date", "team"):
                _optional_string(payload, key)
            _optional_list_of_strings(payload, "outcomes")
        elif category == "role":
            _require_string(payload, "role")
            if "is_current" in payload:
                _require_bool(payload, "is_current")
            for key in ("status", "start_date", "end_date"):
                _optional_string(payload, key)
        elif category == "org":
            _require_string(payload, "org")
            if "is_current" in payload:
                _require_bool(payload, "is_current")
            for key in ("client", "status"):
                _optional_string(payload, key)
        elif category == "project":
            _require_string(payload, "project")
            for key in ("role", "org", "client", "status", "start_date", "end_date", "team"):
                _optional_string(payload, key)
            _optional_list_of_strings(payload, "outcomes")
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
        _optional_list_of_strings(payload, "linked_persons")
        _optional_list_of_strings(payload, "linked_projects")
        _optional_list_of_strings(payload, "event_hierarchy")
        if "event_at" in payload and not isinstance(payload.get("event_at", ""), str):
            raise ValueError("payload.event_at must be a string")
        for key in ("date_range", "location", "lesson", "recurrence"):
            _optional_string(payload, key)
        if "temporal_anchor" in payload and not isinstance(payload.get("temporal_anchor", ""), str):
            raise ValueError("payload.temporal_anchor must be a string")
        if "outcome" in payload and not isinstance(payload.get("outcome", ""), str):
            raise ValueError("payload.outcome must be a string")
        if "valence" in payload:
            _require_string(payload, "valence")
        _optional_number(payload, "intensity")
        return payload

    if domain == "psychometrics":
        _require_string(payload, "framework")
        _require_string(payload, "trait")
        extracted_signal = payload.get("extracted_signal")
        if not isinstance(extracted_signal, dict):
            raise ValueError("payload.extracted_signal must be a dict")
        scored_profile = payload.get("scored_profile")
        if not isinstance(scored_profile, dict):
            raise ValueError("payload.scored_profile must be a dict")
        if not isinstance(payload.get("score"), (int, float)):
            raise ValueError("payload.score must be numeric")
        _require_string(payload, "score_scale")
        _require_string(payload, "direction")
        if not isinstance(payload.get("confidence"), (int, float)):
            raise ValueError("payload.confidence must be numeric")
        _require_string(extracted_signal, "signal_kind")
        if not isinstance(extracted_signal.get("explicit_self_description"), bool):
            raise ValueError("payload.extracted_signal.explicit_self_description must be a bool")
        if not isinstance(extracted_signal.get("signal_confidence"), (int, float)):
            raise ValueError("payload.extracted_signal.signal_confidence must be numeric")
        if not isinstance(extracted_signal.get("evidence_count"), int):
            raise ValueError("payload.extracted_signal.evidence_count must be an int")
        if not isinstance(extracted_signal.get("counterevidence_count"), int):
            raise ValueError("payload.extracted_signal.counterevidence_count must be an int")
        if "observed_at" in extracted_signal and not isinstance(extracted_signal.get("observed_at", ""), str):
            raise ValueError("payload.extracted_signal.observed_at must be a string")
        evidence_quotes = payload.get("evidence_quotes")
        if not isinstance(evidence_quotes, list) or not evidence_quotes:
            raise ValueError("payload.evidence_quotes must be a non-empty list")
        counterevidence_quotes = payload.get("counterevidence_quotes")
        if not isinstance(counterevidence_quotes, list):
            raise ValueError("payload.counterevidence_quotes must be a list")
        if extracted_signal.get("evidence_count") != len(evidence_quotes):
            raise ValueError("payload.extracted_signal.evidence_count must match payload.evidence_quotes")
        if extracted_signal.get("counterevidence_count") != len(counterevidence_quotes):
            raise ValueError("payload.extracted_signal.counterevidence_count must match payload.counterevidence_quotes")
        if extracted_signal.get("evidence_quotes") != evidence_quotes:
            raise ValueError("payload.extracted_signal.evidence_quotes must match payload.evidence_quotes")
        if extracted_signal.get("counterevidence_quotes") != counterevidence_quotes:
            raise ValueError("payload.extracted_signal.counterevidence_quotes must match payload.counterevidence_quotes")
        if not isinstance(scored_profile.get("score"), (int, float)):
            raise ValueError("payload.scored_profile.score must be numeric")
        _require_string(scored_profile, "score_scale")
        _require_string(scored_profile, "direction")
        if not isinstance(scored_profile.get("confidence"), (int, float)):
            raise ValueError("payload.scored_profile.confidence must be numeric")
        if not isinstance(scored_profile.get("framework_threshold"), (int, float)):
            raise ValueError("payload.scored_profile.framework_threshold must be numeric")
        if payload.get("score") != scored_profile.get("score"):
            raise ValueError("payload.score must match payload.scored_profile.score")
        if payload.get("score_scale") != scored_profile.get("score_scale"):
            raise ValueError("payload.score_scale must match payload.scored_profile.score_scale")
        if payload.get("direction") != scored_profile.get("direction"):
            raise ValueError("payload.direction must match payload.scored_profile.direction")
        if payload.get("confidence") != scored_profile.get("confidence"):
            raise ValueError("payload.confidence must match payload.scored_profile.confidence")
        _require_bool(payload, "conservative_update")
        _require_bool(payload, "use_in_generation")
        if payload.get("conservative_update") != scored_profile.get("conservative_update"):
            raise ValueError("payload.conservative_update must match payload.scored_profile.conservative_update")
        if payload.get("use_in_generation") != scored_profile.get("use_in_generation"):
            raise ValueError("payload.use_in_generation must match payload.scored_profile.use_in_generation")
        allowed_generation = (
            (extracted_signal.get("evidence_count", 0) >= 2 or extracted_signal.get("explicit_self_description"))
            and extracted_signal.get("counterevidence_count", 0) == 0
            and float(scored_profile.get("confidence", 0.0)) >= float(scored_profile.get("framework_threshold", 0.0))
        )
        if payload.get("use_in_generation") and not allowed_generation:
            raise ValueError("payload.use_in_generation violates conservative psychometric generation policy")
        if payload.get("conservative_update") is not True:
            raise ValueError("payload.conservative_update must stay true for psychometrics")
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
    if not evidence:
        raise ValueError("candidate evidence must be non-empty")
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("candidate evidence items must be objects")
        quote = item.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("candidate evidence quote must be a non-empty string")
        chunk_kind = item.get("chunk_kind")
        if not isinstance(chunk_kind, str) or not chunk_kind.strip():
            raise ValueError("candidate evidence chunk_kind must be a non-empty string")
        for list_key in ("message_ids", "source_segment_ids", "session_ids"):
            if list_key in item and not isinstance(item.get(list_key), list):
                raise ValueError(f"candidate evidence {list_key} must be a list")
    validate_candidate_payload(
        domain=str(candidate["domain"]),
        category=str(candidate["category"]),
        payload=candidate.get("payload") or {},
    )
    return candidate

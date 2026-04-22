from __future__ import annotations

import json
import pytest

from memco.extractors import ExtractionOrchestrator
from memco.extractors.base import (
    ExtractionContext,
    build_extraction_contract,
    build_extraction_system_prompt,
    build_prompt_payload,
    validate_candidate_payload,
)
from memco.extractors.biography import extract as extract_biography
from memco.extractors.experiences import extract as extract_experiences
from memco.extractors.preferences import extract as extract_preferences
from memco.extractors.psychometrics import extract as extract_psychometrics
from memco.extractors.social_circle import extract as extract_social_circle
from memco.extractors.work import extract as extract_work
from memco.db import get_connection
from memco.repositories.fact_repository import FactRepository
from memco.services.candidate_service import CandidateService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService


def _context(text: str, *, person_id: int | None = 1, resolve_person_id=None) -> ExtractionContext:
    return ExtractionContext(
        text=text,
        subject_key="p1" if person_id is not None else "unknown",
        subject_display="Alice",
        speaker_label="Alice",
        person_id=person_id,
        message_id=11,
        source_segment_id=22,
        session_id=33,
        occurred_at="2026-04-21T10:00:00Z",
        resolve_person_id=resolve_person_id,
    )


def test_extraction_prompt_contract_exposes_llm_first_domain_rules():
    prompt = build_extraction_system_prompt(include_style=False, include_psychometrics=True)

    assert "llm-first structured extraction" in prompt.lower()
    assert "rule-based extraction is fallback-only" in prompt.lower()
    assert "\"domain\": \"biography\"" in prompt
    assert "\"domain\": \"preferences\"" in prompt
    assert "\"domain\": \"social_circle\"" in prompt
    assert "\"domain\": \"work\"" in prompt
    assert "\"domain\": \"experiences\"" in prompt
    assert "\"domain\": \"psychometrics\"" in prompt
    assert "\"negation_rules\"" in prompt
    assert "\"temporal_rules\"" in prompt
    assert "\"evidence_rules\"" in prompt


def test_prompt_payload_embeds_output_contract():
    payload = build_prompt_payload(
        _context("I moved to Lisbon."),
        include_style=False,
        include_psychometrics=True,
    )

    assert payload["contract_version"]
    assert payload["extraction_mode"] == "llm_first_structured_extraction"
    assert payload["output_contract"]["top_level_output"]["required_keys"] == ["items"]
    domains = {item["domain"] for item in payload["output_contract"]["domains"]}
    assert {"biography", "preferences", "social_circle", "work", "experiences", "psychometrics"} <= domains


def test_extract_candidates_from_conversation_returns_typed_p0a_candidates(settings, tmp_path):
    source = tmp_path / "extract.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:01:00Z", "text": "I like tea."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:02:00Z", "text": "Bob is my friend."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingest = IngestService()
    conversation_service = ConversationIngestService()
    extraction = ExtractionService.from_settings(settings)
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        imported = ingest.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        conversation = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        candidates = extraction.extract_candidates_from_conversation(
            conn,
            conversation_id=conversation.conversation_id,
        )

    assert len(candidates) >= 3
    assert "chunk_id" in candidates[0]
    assert "text" in candidates[0]
    domains = {(candidate["domain"], candidate["category"]) for candidate in candidates}
    assert ("biography", "residence") in domains
    assert ("preferences", "preference") in domains
    assert ("social_circle", "friend") in domains
    residence = next(candidate for candidate in candidates if candidate["domain"] == "biography")
    assert residence["payload"]["city"] == "Lisbon"
    assert residence["person_id"] is not None
    social = next(candidate for candidate in candidates if candidate["domain"] == "social_circle")
    assert social["needs_review"] is True
    assert "relation_target_unresolved" in social["reason"]
    assert residence["evidence"][0]["quote"] == "I moved to Lisbon."
    assert residence["evidence"][0]["message_ids"]
    assert residence["evidence"][0]["source_segment_ids"]


def test_extract_candidates_can_include_style_and_psychometrics(settings, tmp_path):
    source = tmp_path / "extract-style.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "Haha, I'm very curious and I really appreciate your help."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingest = IngestService()
    conversation_service = ConversationIngestService()
    extraction = ExtractionService.from_settings(settings)
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        imported = ingest.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        conversation = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        candidates = extraction.extract_candidates_from_conversation(
            conn,
            conversation_id=conversation.conversation_id,
            include_style=True,
            include_psychometrics=True,
        )

    domains = {candidate["domain"] for candidate in candidates}
    assert "style" in domains
    assert "psychometrics" in domains


def test_biography_extractor_returns_residence_candidate():
    candidates = extract_biography(_context("I moved to Lisbon."))

    assert len(candidates) == 1
    assert candidates[0]["domain"] == "biography"
    assert candidates[0]["payload"]["city"] == "Lisbon"


def test_preferences_extractor_returns_preference_candidate():
    candidates = extract_preferences(_context("I prefer tea."))

    assert len(candidates) == 1
    assert candidates[0]["domain"] == "preferences"
    assert candidates[0]["payload"]["value"] == "tea"


def test_social_circle_extractor_marks_unresolved_target_for_review():
    candidates = extract_social_circle(_context("Bob is my friend.", resolve_person_id=lambda label: None))

    assert len(candidates) == 1
    assert candidates[0]["domain"] == "social_circle"
    assert candidates[0]["needs_review"] is True
    assert "relation_target_unresolved" in candidates[0]["reason"]


def test_work_extractor_returns_employment_and_skill_candidates():
    candidates = extract_work(_context("I work as an engineer and I use Python."))

    categories = {(candidate["domain"], candidate["category"]) for candidate in candidates}
    assert ("work", "employment") in categories
    assert ("work", "tool") in categories


def test_experiences_extractor_returns_event_candidate():
    candidates = extract_experiences(_context("I attended PyCon in 2025."))

    assert len(candidates) == 1
    assert candidates[0]["domain"] == "experiences"
    assert candidates[0]["payload"]["event"] == "PyCon"
    assert candidates[0]["payload"]["event_at"] == "2025"


def test_psychometrics_extractor_returns_trait_candidate():
    candidates = extract_psychometrics(_context("I'm very curious."))

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert candidates[0]["domain"] == "psychometrics"
    assert payload["trait"] == "openness"
    assert payload["framework"] == "big_five"
    assert payload["evidence_quotes"] != []
    assert payload["counterevidence_quotes"] == []
    assert payload["extracted_signal"]["signal_kind"] == "explicit_self_description"
    assert payload["scored_profile"]["conservative_update"] is True
    assert payload["use_in_generation"] is True
    assert "stub" not in payload["safety_notes"].lower()


def test_psychometrics_extractor_supports_schwartz_values():
    candidates = extract_psychometrics(_context("I value independence."))

    assert len(candidates) == 1
    assert candidates[0]["payload"]["framework"] == "schwartz_values"
    assert candidates[0]["payload"]["trait"] == "self_direction"


def test_psychometrics_extractor_supports_extended_frameworks():
    examples = [
        ("I feel excited about life.", "panas", "positive_affect"),
        ("I try to be kind to everyone.", "via", "kindness"),
        ("I easily feel what others feel.", "iri", "empathic_concern"),
        ("I believe caring for others matters most.", "moral_foundations", "care"),
        ("I favor limited government intervention.", "political_compass", "libertarian"),
        ("I follow rules because they keep society working.", "kohlberg", "conventional_reasoning"),
        ("I solve complex logic puzzles quickly.", "cognitive_ability_profile", "analytical_reasoning"),
    ]

    for text, framework, trait in examples:
        candidates = extract_psychometrics(_context(text))
        assert len(candidates) == 1
        assert candidates[0]["payload"]["framework"] == framework
        assert candidates[0]["payload"]["trait"] == trait


def test_psychometrics_extractor_accumulates_multiple_framework_matches():
    candidates = extract_psychometrics(_context("I'm very curious and I value independence."))

    frameworks = {candidate["payload"]["framework"] for candidate in candidates}
    assert frameworks == {"big_five", "schwartz_values"}


def test_psychometrics_extractor_separates_signal_from_scored_profile():
    candidates = extract_psychometrics(_context("I'm very curious."))

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["extracted_signal"]["evidence_quotes"] == payload["evidence_quotes"]
    assert payload["extracted_signal"]["counterevidence_quotes"] == payload["counterevidence_quotes"]
    assert payload["scored_profile"]["score"] == payload["score"]
    assert payload["scored_profile"]["confidence"] == payload["confidence"]
    assert payload["scored_profile"]["use_in_generation"] == payload["use_in_generation"]


def test_psychometrics_behavioral_hint_stays_conservative_for_generation():
    candidates = extract_psychometrics(_context("I feel excited about life."))

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["extracted_signal"]["signal_kind"] == "behavioral_hint"
    assert payload["use_in_generation"] is False


def test_psychometrics_scoring_layer_aggregates_multiple_supporting_signals():
    candidates = extract_psychometrics(_context("I try to be kind and I help people when they struggle."))

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["framework"] == "via"
    assert payload["trait"] == "kindness"
    assert payload["extracted_signal"]["evidence_count"] == 2
    assert payload["scored_profile"]["score"] > payload["extracted_signal"]["signal_confidence"]
    assert payload["use_in_generation"] is True


def test_orchestrator_combines_core_and_optional_extractors():
    orchestrator = ExtractionOrchestrator()
    candidates = orchestrator.extract(
        _context("I moved to Lisbon. I prefer tea. Bob is my friend. Haha, I'm very curious."),
        include_style=True,
        include_psychometrics=True,
    )

    domains = {candidate["domain"] for candidate in candidates}
    assert {"biography", "preferences", "social_circle", "style", "psychometrics"} <= domains


def test_biography_extractor_covers_origin_languages_pets_and_goals():
    contexts = [
        _context("I'm from Canada."),
        _context("I speak English and Spanish."),
        _context("My dog is Bruno."),
        _context("My goal is to run a marathon."),
    ]

    candidates = [candidate for context in contexts for candidate in extract_biography(context)]
    categories = {(candidate["category"], candidate["subcategory"]) for candidate in candidates}

    assert ("origin", "") in categories
    assert ("languages", "") in categories
    assert ("pets", "") in categories
    assert ("goals", "") in categories
    origin = next(candidate for candidate in candidates if candidate["category"] == "origin")
    languages = next(candidate for candidate in candidates if candidate["category"] == "languages")
    pet = next(candidate for candidate in candidates if candidate["category"] == "pets")
    goal = next(candidate for candidate in candidates if candidate["category"] == "goals")
    assert origin["payload"]["place"] == "Canada"
    assert languages["payload"]["languages"] == ["English", "Spanish"]
    assert pet["payload"]["pet_type"] == "dog"
    assert pet["payload"]["pet_name"] == "Bruno"
    assert goal["payload"]["goal"] == "run a marathon"


def test_biography_extractor_covers_identity_education_family_habits_and_constraints():
    contexts = [
        _context("My name is Alice Example."),
        _context("I studied computer science at MIT."),
        _context("My sister is Emma."),
        _context("I usually wake up at 6am."),
        _context("I can't eat gluten."),
    ]

    candidates = [candidate for context in contexts for candidate in extract_biography(context)]
    categories = {(candidate["category"], candidate["subcategory"]) for candidate in candidates}

    assert ("identity", "") in categories
    assert ("education", "") in categories
    assert ("family", "sister") in categories
    assert ("habits", "") in categories
    assert ("constraints", "") in categories


def test_preferences_extractor_tracks_polarity_strength_and_reason():
    candidates = extract_preferences(_context("I strongly dislike coffee because it makes me anxious."))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["payload"]["value"] == "coffee"
    assert candidate["payload"]["polarity"] == "dislike"
    assert candidate["payload"]["strength"] == "strong"
    assert candidate["payload"]["reason"] == "it makes me anxious"


def test_preferences_extractor_marks_past_preference_as_not_current():
    candidates = extract_preferences(_context("I used to like tea."))

    assert len(candidates) == 1
    assert candidates[0]["payload"]["value"] == "tea"
    assert candidates[0]["payload"]["is_current"] is False


def test_preferences_extractor_handles_negated_preference_as_dislike():
    candidates = extract_preferences(_context("I don't like sushi because it feels too heavy."))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["payload"]["value"] == "sushi"
    assert candidate["payload"]["polarity"] == "dislike"
    assert candidate["payload"]["is_current"] is True
    assert candidate["summary"].lower().startswith("alice dislikes")


def test_preferences_extractor_prefers_current_self_correction():
    candidates = extract_preferences(_context("I used to like tea, but now I prefer coffee."))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["payload"]["value"] == "coffee"
    assert candidate["payload"]["is_current"] is True


def test_preferences_extractor_supports_indirect_go_to_phrase():
    candidates = extract_preferences(_context("Tea is my go-to drink when I need to focus."))

    assert len(candidates) == 1
    assert candidates[0]["payload"]["value"] == "Tea"
    assert candidates[0]["payload"]["polarity"] == "like"


def test_social_circle_extractor_captures_current_flag_and_relationship_event():
    contexts = [
        _context("Bob is my friend.", resolve_person_id=lambda label: 7),
        _context("Alice used to be my manager."),
    ]

    candidates = [candidate for context in contexts for candidate in extract_social_circle(context)]
    friend = next(candidate for candidate in candidates if candidate["category"] == "friend")
    manager = next(candidate for candidate in candidates if candidate["category"] == "manager")

    assert friend["payload"]["target_person_id"] == 7
    assert friend["payload"]["is_current"] is True
    assert manager["payload"]["is_current"] is False
    assert manager["payload"]["target_label"] == "Alice"


def test_social_circle_extractor_captures_relationship_event():
    candidates = extract_social_circle(_context("I met Bob at work.", resolve_person_id=lambda label: 7))

    assert len(candidates) == 1
    assert candidates[0]["category"] == "relationship_event"
    assert candidates[0]["payload"]["event"] == "met"
    assert candidates[0]["payload"]["context"] == "work"


def test_work_extractor_covers_org_project_tool_and_current_flag():
    candidates = extract_work(
        _context(
            "I work at OpenAI. I'm a researcher. I use Python. I'm building Memco.",
        )
    )

    categories = {(candidate["category"], candidate["subcategory"]) for candidate in candidates}
    assert ("employment", "") in categories
    assert ("org", "") in categories
    assert ("tool", "") in categories or ("skill", "") in categories
    assert ("project", "") in categories
    employment = next(candidate for candidate in candidates if candidate["category"] == "employment")
    org = next(candidate for candidate in candidates if candidate["category"] == "org")
    project = next(candidate for candidate in candidates if candidate["category"] == "project")
    assert employment["payload"]["title"] == "researcher"
    assert employment["payload"]["is_current"] is True
    assert org["payload"]["org"] == "OpenAI"
    assert project["payload"]["project"] == "Memco"


def test_work_extractor_captures_role_skill_and_past_context():
    candidates = extract_work(_context("I used to be a teacher. I know SQL."))

    categories = {candidate["category"] for candidate in candidates}
    assert "role" in categories
    assert "skill" in categories
    role = next(candidate for candidate in candidates if candidate["category"] == "role")
    skill = next(candidate for candidate in candidates if candidate["category"] == "skill")
    assert role["payload"]["is_current"] is False
    assert skill["payload"]["skill"] == "SQL"


def test_experiences_extractor_captures_summary_time_participants_outcome_and_valence():
    candidates = extract_experiences(
        _context("I attended PyCon with Bob in 2024 and it was great because we won the hackathon.")
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["payload"]["event"] == "PyCon"
    assert candidate["payload"]["participants"] == ["Bob"]
    assert candidate["payload"]["event_at"] == "2024"
    assert candidate["payload"]["outcome"] == "won the hackathon"
    assert candidate["payload"]["valence"] == "positive"


def test_extractors_support_russian_and_mixed_language_inputs():
    biography = extract_biography(_context("Я живу в Lisbon."))
    preferences = extract_preferences(_context("Я предпочитаю tea."))
    work = extract_work(_context("Я работаю в OpenAI."))
    experiences = extract_experiences(_context("Я был на PyCon в 2024."))
    social = extract_social_circle(_context("Bob мой друг.", resolve_person_id=lambda label: 7))

    assert biography[0]["payload"]["city"] == "Lisbon"
    assert preferences[0]["payload"]["value"] == "tea"
    assert work[0]["payload"]["org"] == "OpenAI"
    assert experiences[0]["payload"]["event"] == "PyCon"
    assert experiences[0]["payload"]["event_at"] == "2024"
    assert social[0]["payload"]["target_label"] == "Bob"
    assert social[0]["payload"]["target_person_id"] == 7


def test_biography_extractor_supports_indirect_residence_and_skips_hypothetical_move():
    indirect = extract_biography(_context("Lisbon is my base these days."))
    hypothetical = extract_biography(_context("I might move to Berlin next year."))

    assert len(indirect) == 1
    assert indirect[0]["payload"]["city"] == "Lisbon"
    assert hypothetical == []


def test_experiences_extractor_uses_temporal_anchor_for_approximate_dates():
    candidates = extract_experiences(_context("I attended PyCon around 2024 with Bob and it was great."))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["payload"]["event"] == "PyCon"
    assert candidate["payload"]["event_at"] == ""
    assert candidate["payload"]["temporal_anchor"] == "around 2024"


def test_validate_candidate_payload_rejects_wrong_domain_shape():
    try:
        validate_candidate_payload(domain="biography", category="residence", payload={"place": "Lisbon"})
    except ValueError as exc:
        assert "payload.city" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected payload validation failure")


def test_validate_candidate_payload_rejects_inconsistent_psychometric_counts():
    payload = {
        "framework": "big_five",
        "trait": "openness",
        "extracted_signal": {
            "signal_kind": "explicit_self_description",
            "explicit_self_description": True,
            "signal_confidence": 0.72,
            "evidence_count": 2,
            "counterevidence_count": 0,
            "evidence_quotes": [{"quote": "I am curious.", "message_ids": ["1"], "interpretation": "signal"}],
            "counterevidence_quotes": [],
            "observed_at": "2026-04-21T10:00:00Z",
        },
        "scored_profile": {
            "score": 0.8,
            "score_scale": "0_1",
            "direction": "high",
            "confidence": 0.76,
            "framework_threshold": 0.7,
            "conservative_update": True,
            "use_in_generation": True,
        },
        "score": 0.8,
        "score_scale": "0_1",
        "direction": "high",
        "confidence": 0.76,
        "evidence_quotes": [{"quote": "I am curious.", "message_ids": ["1"], "interpretation": "signal"}],
        "counterevidence_quotes": [],
        "conservative_update": True,
        "use_in_generation": True,
        "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
    }

    with pytest.raises(ValueError, match="evidence_count"):
        validate_candidate_payload(domain="psychometrics", category="trait", payload=payload)


def test_validate_candidate_payload_rejects_unsafe_psychometric_generation_flag():
    payload = {
        "framework": "panas",
        "trait": "positive_affect",
        "extracted_signal": {
            "signal_kind": "behavioral_hint",
            "explicit_self_description": False,
            "signal_confidence": 0.52,
            "evidence_count": 1,
            "counterevidence_count": 1,
            "evidence_quotes": [{"quote": "I feel excited.", "message_ids": ["1"], "interpretation": "signal"}],
            "counterevidence_quotes": [{"quote": "but sometimes I shut down", "message_ids": ["1"], "interpretation": "counter"}],
            "observed_at": "2026-04-21T10:00:00Z",
        },
        "scored_profile": {
            "score": 0.7,
            "score_scale": "0_1",
            "direction": "high",
            "confidence": 0.82,
            "framework_threshold": 0.75,
            "conservative_update": True,
            "use_in_generation": True,
        },
        "score": 0.7,
        "score_scale": "0_1",
        "direction": "high",
        "confidence": 0.82,
        "evidence_quotes": [{"quote": "I feel excited.", "message_ids": ["1"], "interpretation": "signal"}],
        "counterevidence_quotes": [{"quote": "but sometimes I shut down", "message_ids": ["1"], "interpretation": "counter"}],
        "conservative_update": True,
        "use_in_generation": True,
        "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
    }

    with pytest.raises(ValueError, match="violates conservative psychometric generation policy"):
        validate_candidate_payload(domain="psychometrics", category="trait", payload=payload)


def test_extraction_service_requires_explicit_runtime_wiring():
    try:
        ExtractionService()
    except ValueError as exc:
        assert "requires explicit settings or llm_provider" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected explicit runtime wiring failure")


def test_candidate_service_requires_explicit_extraction_service_for_extraction():
    service = CandidateService()

    try:
        service.extract_from_conversation(None, workspace_slug="default", conversation_id=1)
    except ValueError as exc:
        assert "requires an explicit ExtractionService" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected explicit extraction service failure")

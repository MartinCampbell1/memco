from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.extractors.base import ExtractionContext
from memco.extractors.psychometrics import extract as extract_psychometrics
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _actor(settings, **overrides):
    actor_id = overrides.get("actor_id", "dev-owner")
    policy = settings.api.actor_policies[actor_id]
    return {
        "actor_id": actor_id,
        "actor_type": policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": policy.can_view_sensitive,
        **overrides,
    }


def test_style_and_psychometrics_do_not_answer_factual_questions(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/style-psy.md",
            source_type="note",
            origin_uri="/tmp/style-psy.md",
            title="style-psy",
            sha256="style-psy-sha",
            parsed_text="Haha, I am very curious.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="style",
                category="communication_style",
                canonical_key="alice:style:communication_style:humorous",
                payload={"tone": "humorous", "generation_guidance": "Use light humor."},
                summary="Alice often communicates humorously.",
                confidence=0.6,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Haha",
            ),
            locator={"message_ids": ["1"]},
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="psychometrics",
                category="trait",
                subcategory="big_five",
                canonical_key="alice:psychometrics:big_five:openness",
                payload={
                    "framework": "big_five",
                    "trait": "openness",
                    "extracted_signal": {
                        "signal_kind": "explicit_self_description",
                        "explicit_self_description": True,
                        "signal_confidence": 0.72,
                        "evidence_count": 1,
                        "counterevidence_count": 1,
                        "evidence_quotes": [
                            {"quote": "I am very curious.", "message_ids": ["2"], "interpretation": "Possible signal for openness."}
                        ],
                        "counterevidence_quotes": [
                            {
                                "quote": "I am very curious.",
                                "message_ids": ["2"],
                                "interpretation": "No direct counterevidence found in this snippet; update conservatively for openness.",
                            }
                        ],
                        "observed_at": "2026-04-21T10:01:00Z",
                    },
                    "scored_profile": {
                        "score": 0.7,
                        "score_scale": "0_1",
                        "direction": "high",
                        "confidence": 0.55,
                        "framework_threshold": 0.7,
                        "conservative_update": True,
                        "use_in_generation": False,
                    },
                    "score": 0.7,
                    "score_scale": "0_1",
                    "direction": "high",
                    "confidence": 0.55,
                    "evidence_quotes": [
                        {"quote": "I am very curious.", "message_ids": ["2"], "interpretation": "Possible signal for openness."}
                    ],
                    "counterevidence_quotes": [
                        {
                            "quote": "I am very curious.",
                            "message_ids": ["2"],
                            "interpretation": "No direct counterevidence found in this snippet; update conservatively for openness.",
                        }
                    ],
                    "conservative_update": True,
                    "last_updated": "2026-04-21T10:01:00Z",
                    "use_in_generation": False,
                    "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
                },
                summary="Alice may score high on openness.",
                confidence=0.55,
                observed_at="2026-04-21T10:01:00Z",
                source_id=source_id,
                quote_text="I am very curious.",
            ),
            locator={"message_ids": ["2"]},
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Does Alice own a cat?", "actor": _actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["retrieval"]["hits"] == []


def test_psychometric_records_use_evidence_and_counterevidence_fields():
    candidates = extract_psychometrics(
        ExtractionContext(
            text="I'm very curious, but sometimes I avoid new experiences.",
            subject_key="p1",
            subject_display="Alice",
            speaker_label="Alice",
            person_id=1,
            message_id=1,
            source_segment_id=2,
            session_id=3,
            occurred_at="2026-04-21T10:00:00Z",
        )
    )

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["evidence_quotes"] != []
    assert payload["counterevidence_quotes"] != []
    assert payload["extracted_signal"]["evidence_quotes"] == payload["evidence_quotes"]
    assert payload["extracted_signal"]["counterevidence_quotes"] == payload["counterevidence_quotes"]
    assert payload["scored_profile"]["confidence"] == payload["confidence"]
    assert payload["conservative_update"] is True
    assert payload["use_in_generation"] is False


def test_low_confidence_psychometric_trait_does_not_enable_generation_hint():
    candidates = extract_psychometrics(
        ExtractionContext(
            text="I feel excited about life.",
            subject_key="unknown",
            subject_display="Unknown speaker",
            speaker_label="",
            person_id=None,
            message_id=1,
            source_segment_id=2,
            session_id=3,
            occurred_at="2026-04-21T10:00:00Z",
        )
    )

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["confidence"] < 0.5
    assert payload["extracted_signal"]["signal_kind"] == "behavioral_hint"
    assert payload["use_in_generation"] is False


def test_counterevidence_reduces_confidence_for_resolved_psychometric_trait():
    candidates = extract_psychometrics(
        ExtractionContext(
            text="I'm very curious, but sometimes I avoid new experiences.",
            subject_key="p1",
            subject_display="Alice",
            speaker_label="Alice",
            person_id=1,
            message_id=1,
            source_segment_id=2,
            session_id=3,
            occurred_at="2026-04-21T10:00:00Z",
        )
    )

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["confidence"] < 0.55
    assert payload["extracted_signal"]["counterevidence_count"] == 1
    assert payload["scored_profile"]["conservative_update"] is True
    assert payload["use_in_generation"] is False


def test_multiple_frameworks_in_one_snippet_stay_conservative():
    candidates = extract_psychometrics(
        ExtractionContext(
            text="I'm very curious and I value independence, but sometimes I avoid new experiences.",
            subject_key="p1",
            subject_display="Alice",
            speaker_label="Alice",
            person_id=1,
            message_id=1,
            source_segment_id=2,
            session_id=3,
            occurred_at="2026-04-21T10:00:00Z",
        )
    )

    frameworks = {candidate["payload"]["framework"] for candidate in candidates}
    assert frameworks == {"big_five", "schwartz_values"}
    for candidate in candidates:
        payload = candidate["payload"]
        assert payload["extracted_signal"]["counterevidence_count"] == 1
        assert payload["use_in_generation"] is False


def test_psychometrics_do_not_surface_in_retrieve_results(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/psy-only.md",
            source_type="note",
            origin_uri="/tmp/psy-only.md",
            title="psy-only",
            sha256="psy-only-sha",
            parsed_text="I am very curious.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="psychometrics",
                category="trait",
                subcategory="big_five",
                canonical_key="alice:psychometrics:big_five:openness",
                payload={
                    "framework": "big_five",
                    "trait": "openness",
                    "extracted_signal": {
                        "signal_kind": "explicit_self_description",
                        "explicit_self_description": True,
                        "signal_confidence": 0.72,
                        "evidence_count": 1,
                        "counterevidence_count": 0,
                        "evidence_quotes": [
                            {"quote": "I am very curious.", "message_ids": ["1"], "interpretation": "Possible signal for openness."}
                        ],
                        "counterevidence_quotes": [],
                        "observed_at": "2026-04-21T10:00:00Z",
                    },
                    "scored_profile": {
                        "score": 0.7,
                        "score_scale": "0_1",
                        "direction": "high",
                        "confidence": 0.55,
                        "framework_threshold": 0.7,
                        "conservative_update": True,
                        "use_in_generation": False,
                    },
                    "score": 0.7,
                    "score_scale": "0_1",
                    "direction": "high",
                    "confidence": 0.55,
                    "evidence_quotes": [
                        {"quote": "I am very curious.", "message_ids": ["1"], "interpretation": "Possible signal for openness."}
                    ],
                    "counterevidence_quotes": [],
                    "conservative_update": True,
                    "last_updated": "2026-04-21T10:00:00Z",
                    "use_in_generation": False,
                    "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
                },
                summary="Alice may score high on openness.",
                confidence=0.55,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="I am very curious.",
            ),
            locator={"message_ids": ["1"]},
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "psychometrics",
            "query": "What psychometric trait might Alice have?",
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["hits"] == []
    assert payload["support_level"] == "unsupported"

    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "What kind of person is Alice?",
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    chat_payload = response.json()
    assert chat_payload["refused"] is True
    assert chat_payload["retrieval"]["hits"] == []
    assert "openness" not in chat_payload["answer"].lower()

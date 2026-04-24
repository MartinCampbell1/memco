from __future__ import annotations

import json
from pathlib import Path

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
from memco.llm import LLMJSONResponse, LLMTextResponse, LLMUsage
from memco.repositories.fact_repository import FactRepository
from memco.services.candidate_service import CandidateService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.services.pipeline_service import IngestPipelineService


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


class _RecordingExtractionProvider:
    name = "recording"
    model = "fixture"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def count_tokens(self, *, text: str) -> int:
        return max(1, len(text.split()))

    def estimate_cost(self, *, input_tokens: int, output_tokens: int) -> float | None:
        return 0.0

    def complete_text(self, *, system_prompt: str, prompt: str, metadata: dict | None = None) -> LLMTextResponse:
        return LLMTextResponse(
            text=prompt,
            usage=LLMUsage(input_tokens=self.count_tokens(text=prompt), output_tokens=1, estimated_cost_usd=0.0),
            provider=self.name,
            model=self.model,
        )

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict | None = None,
    ) -> LLMJSONResponse:
        payload = json.loads(prompt)
        call = {"payload": payload, "metadata": metadata or {}}
        self.calls.append(call)
        items: list[dict] = []
        chunk = payload.get("chunk")
        if isinstance(chunk, dict) and chunk.get("chunk_kind") == "conversation" and payload["speaker_label"] == "Alice":
            messages = chunk.get("messages") or []
            if any("I moved there" in message.get("text", "") for message in messages) and any(
                "You mean Lisbon" in message.get("text", "") for message in messages
            ):
                items.append(
                    {
                        "domain": "biography",
                        "category": "residence",
                        "subcategory": "city",
                        "canonical_key": f"{payload['subject_key']}:biography:residence:lisbon",
                        "payload": {"city": "Lisbon", "valid_from": "2024"},
                        "summary": "Alice lives in Lisbon.",
                        "confidence": 0.9,
                        "reason": "",
                        "needs_review": False,
                        "evidence": [
                            {
                                "quote": "\n".join(
                                    f"{message['speaker_label']}: {message['text']}" for message in messages
                                ),
                                "message_ids": [str(message["message_id"]) for message in messages],
                                "source_segment_ids": list(chunk["source_segment_ids"]),
                                "session_ids": [
                                    int(message["session_id"])
                                    for message in messages
                                    if message.get("session_id") is not None
                                ],
                                "chunk_kind": "conversation",
                            }
                        ],
                    }
                )
        if isinstance(chunk, dict) and chunk.get("chunk_kind") == "source" and "Alice moved to Lisbon" in payload["text"]:
            items.append(
                {
                    "domain": "biography",
                    "category": "residence",
                    "subcategory": "city",
                    "canonical_key": f"{payload['subject_key']}:biography:residence:lisbon",
                    "payload": {"city": "Lisbon", "valid_from": "2024"},
                    "summary": "Alice lives in Lisbon.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": [
                        {
                            "quote": payload["text"],
                            "message_ids": [],
                            "source_segment_ids": list(chunk["source_segment_ids"]),
                            "session_ids": [],
                            "chunk_kind": "source",
                        }
                    ],
                }
            )
        raw_text = json.dumps({"items": items}, ensure_ascii=False)
        return LLMJSONResponse(
            content={"items": items},
            raw_text=raw_text,
            usage=LLMUsage(
                input_tokens=self.count_tokens(text=system_prompt) + self.count_tokens(text=prompt),
                output_tokens=self.count_tokens(text=raw_text),
                estimated_cost_usd=0.0,
            ),
            provider=self.name,
            model=self.model,
        )


class _EmptyChunkProvenanceProvider(_RecordingExtractionProvider):
    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict | None = None,
    ) -> LLMJSONResponse:
        payload = json.loads(prompt)
        self.calls.append({"payload": payload, "metadata": metadata or {}})
        items: list[dict] = []
        chunk = payload.get("chunk")
        if isinstance(chunk, dict) and chunk.get("chunk_kind") == "conversation" and payload["speaker_label"] == "Alice":
            items.append(
                {
                    "domain": "biography",
                    "category": "residence",
                    "subcategory": "city",
                    "canonical_key": f"{payload['subject_key']}:biography:residence:lisbon",
                    "payload": {"city": "Lisbon"},
                    "summary": "Alice lives in Lisbon.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": [
                        {
                            "quote": "I live in Lisbon.",
                            "message_ids": [],
                            "source_segment_ids": [],
                            "session_ids": [],
                            "chunk_kind": "conversation",
                        }
                    ],
                }
            )
        raw_text = json.dumps({"items": items}, ensure_ascii=False)
        return LLMJSONResponse(
            content={"items": items},
            raw_text=raw_text,
            usage=LLMUsage(
                input_tokens=self.count_tokens(text=system_prompt) + self.count_tokens(text=prompt),
                output_tokens=self.count_tokens(text=raw_text),
                estimated_cost_usd=0.0,
            ),
            provider=self.name,
            model=self.model,
        )


class _InvalidThenValidChunkProvider(_EmptyChunkProvenanceProvider):
    def complete_json(self, **kwargs) -> LLMJSONResponse:
        response = super().complete_json(**kwargs)
        if isinstance(response.content, dict) and response.content.get("items"):
            items = [{"domain": "biography"}, *response.content["items"]]
            raw_text = json.dumps({"items": items}, ensure_ascii=False)
            return LLMJSONResponse(
                content={"items": items},
                raw_text=raw_text,
                usage=response.usage,
                provider=response.provider,
                model=response.model,
            )
        return response


class _NonObjectThenValidChunkProvider(_EmptyChunkProvenanceProvider):
    def complete_json(self, **kwargs) -> LLMJSONResponse:
        response = super().complete_json(**kwargs)
        if isinstance(response.content, dict) and response.content.get("items"):
            items = [None, "not-a-candidate", *response.content["items"]]
            raw_text = json.dumps({"items": items}, ensure_ascii=False)
            return LLMJSONResponse(
                content={"items": items},
                raw_text=raw_text,
                usage=response.usage,
                provider=response.provider,
                model=response.model,
            )
        return response


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
    assert payload["json_output_required"] is True
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


def test_audit_fixture_deterministic_extraction_keeps_atomic_payloads(settings, tmp_path):
    source = tmp_path / "audit-fixture.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:00:00Z", "text": "My name is Alice and I moved to Lisbon in 2024."},
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:01:00Z", "text": "I work as a software engineer at Acme Robotics."},
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:02:00Z", "text": "I love sushi and I prefer green tea."},
                    {"speaker": "Bob", "timestamp": "2026-01-01T10:03:00Z", "text": "I live in Porto and I prefer coffee."},
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:04:00Z", "text": "My sister is Maria."},
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:05:00Z", "text": "I attended PyCon in 2025."},
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
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
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

    alice_identity = next(
        candidate for candidate in candidates if candidate["domain"] == "biography" and candidate["category"] == "identity"
    )
    alice_residence = next(
        candidate
        for candidate in candidates
        if candidate["domain"] == "biography" and candidate["category"] == "residence" and candidate["speaker_label"] == "Alice"
    )
    bob_residence = next(
        candidate
        for candidate in candidates
        if candidate["domain"] == "biography" and candidate["category"] == "residence" and candidate["speaker_label"] == "Bob"
    )
    employment = next(candidate for candidate in candidates if candidate["domain"] == "work" and candidate["category"] == "employment")
    preferences = {
        (candidate["speaker_label"], candidate["payload"]["value"])
        for candidate in candidates
        if candidate["domain"] == "preferences"
    }

    assert alice_identity["payload"]["name"] == "Alice"
    assert alice_identity["needs_review"] is False
    assert alice_residence["payload"] == {"city": "Lisbon", "valid_from": "2024"}
    assert alice_residence["needs_review"] is False
    assert bob_residence["payload"]["city"] == "Porto"
    assert bob_residence["needs_review"] is False
    assert employment["payload"]["title"] == "software engineer"
    assert employment["payload"]["role"] == "software engineer"
    assert employment["payload"]["org"] == "Acme Robotics"
    assert employment["needs_review"] is False
    assert ("Alice", "sushi") in preferences
    assert ("Alice", "green tea") in preferences
    assert ("Bob", "coffee") in preferences


def test_chunk_window_extraction_uses_neighboring_messages(settings, tmp_path):
    source = tmp_path / "chunk-window.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:00:00Z", "text": "I moved there in 2024."},
                    {"speaker": "Bob", "timestamp": "2026-01-01T10:01:00Z", "text": "Lisbon, right?"},
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:02:00Z", "text": "Yes."},
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
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
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

    residences = [
        candidate
        for candidate in candidates
        if candidate["domain"] == "biography" and candidate["category"] == "residence"
    ]
    assert len(residences) == 1
    residence = residences[0]
    assert residence["payload"] == {"city": "Lisbon", "valid_from": "2024"}
    assert residence["person_id"] is not None
    assert residence["chunk_id"] is not None
    assert residence["message_id"] is not None
    assert residence["evidence"][0]["message_ids"]
    assert len(residence["evidence"][0]["source_segment_ids"]) == 3


def test_provider_receives_conversation_chunk_payload(settings, tmp_path):
    source = tmp_path / "provider-chunk-window.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:00:00Z", "text": "I moved there in 2024."},
                    {"speaker": "Bob", "timestamp": "2026-01-01T10:01:00Z", "text": "You mean Lisbon?"},
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:02:00Z", "text": "Yes."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingest = IngestService()
    conversation_service = ConversationIngestService()
    provider = _RecordingExtractionProvider()
    extraction = ExtractionService(llm_provider=provider)

    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
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

    alice_calls = [
        call
        for call in provider.calls
        if call["payload"]["speaker_label"] == "Alice" and isinstance(call["payload"].get("chunk"), dict)
    ]
    assert alice_calls
    alice_payload = alice_calls[0]["payload"]
    alice_metadata = alice_calls[0]["metadata"]
    assert alice_payload["message_id"] is None
    assert alice_metadata["message_id"] is None
    assert alice_payload["chunk"]["chunk_kind"] == "conversation"
    assert [message["text"] for message in alice_payload["chunk"]["messages"]] == [
        "I moved there in 2024.",
        "You mean Lisbon?",
        "Yes.",
    ]
    assert alice_payload["chunk"]["target_message_ids"]
    assert alice_metadata["target_message_ids"] == alice_payload["chunk"]["target_message_ids"]
    assert all(call["metadata"]["message_id"] is None for call in provider.calls)
    residence = next(candidate for candidate in candidates if candidate["domain"] == "biography")
    assert residence["payload"] == {"city": "Lisbon", "valid_from": "2024"}
    assert len(residence["evidence"][0]["source_segment_ids"]) == 3


def test_pipeline_backfills_empty_provider_chunk_provenance(settings, tmp_path):
    source = tmp_path / "provider-empty-provenance.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:00:00Z", "text": "I live in Lisbon."},
                    {"speaker": "Bob", "timestamp": "2026-01-01T10:01:00Z", "text": "Noted."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    provider = _EmptyChunkProvenanceProvider()
    pipeline = IngestPipelineService(
        candidate_service=CandidateService(extraction_service=ExtractionService(llm_provider=provider))
    )

    with get_connection(settings.db_path) as conn:
        result = pipeline.ingest_path(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
            person_display_name="Alice",
            person_slug="alice",
            aliases=["Alice"],
        )

    assert result["publish_errors"] == []
    assert len(result["published"]) == 1
    candidate_evidence = result["published"][0]["candidate"]["evidence"][0]
    fact_evidence = result["published"][0]["fact"]["evidence"][0]
    assert candidate_evidence["source_segment_ids"]
    assert candidate_evidence["message_ids"]
    assert fact_evidence["source_segment_id"] is not None


def test_pipeline_skips_invalid_provider_chunk_candidates(settings, tmp_path):
    source = tmp_path / "provider-invalid-candidate.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:00:00Z", "text": "I live in Lisbon."},
                    {"speaker": "Bob", "timestamp": "2026-01-01T10:01:00Z", "text": "Noted."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pipeline = IngestPipelineService(
        candidate_service=CandidateService(extraction_service=ExtractionService(llm_provider=_InvalidThenValidChunkProvider()))
    )

    with get_connection(settings.db_path) as conn:
        result = pipeline.ingest_path(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
            person_display_name="Alice",
            person_slug="alice",
            aliases=["Alice"],
        )

    assert result["publish_errors"] == []
    assert len(result["published"]) == 1


def test_pipeline_skips_non_object_provider_chunk_candidates(settings, tmp_path):
    source = tmp_path / "provider-non-object-candidate.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-01-01T10:00:00Z", "text": "I live in Lisbon."},
                    {"speaker": "Bob", "timestamp": "2026-01-01T10:01:00Z", "text": "Noted."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pipeline = IngestPipelineService(
        candidate_service=CandidateService(extraction_service=ExtractionService(llm_provider=_NonObjectThenValidChunkProvider()))
    )

    with get_connection(settings.db_path) as conn:
        result = pipeline.ingest_path(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
            person_display_name="Alice",
            person_slug="alice",
            aliases=["Alice"],
        )

    assert result["publish_errors"] == []
    assert len(result["published"]) == 1


def test_provider_optional_string_noise_is_removed_before_validation(settings):
    extraction = ExtractionService.from_settings(settings)

    normalized = extraction._normalize_provider_candidate(
        candidate={
            "domain": "work",
            "category": "employment",
            "subcategory": "",
            "canonical_key": "alice:work:employment:designer",
            "payload": {"title": "product designer", "client": {"name": "Acme"}, "status": ""},
            "summary": "Alice works as a product designer.",
            "confidence": 0.9,
            "reason": "",
            "needs_review": False,
            "evidence": [
                {
                    "quote": "I am a product designer.",
                    "message_ids": ["1"],
                    "source_segment_ids": [1],
                    "chunk_kind": "conversation",
                }
            ],
        },
        text="I am a product designer.",
        subject_display="Alice",
        person_id=1,
        message_id=1,
        source_segment_id=1,
        session_id=1,
    )

    assert "client" not in normalized["payload"]
    assert "status" not in normalized["payload"]
    validate_candidate_payload(
        domain=normalized["domain"],
        category=normalized["category"],
        payload=normalized["payload"],
    )

    event = extraction._normalize_provider_candidate(
        candidate={
            "domain": "experiences",
            "category": "event",
            "subcategory": "",
            "canonical_key": "alice:experiences:event:pycon",
            "payload": {"event": "attended PyCon", "linked_projects": {"name": "Memco"}},
            "summary": "Alice attended PyCon.",
            "confidence": 0.9,
            "reason": "",
            "needs_review": False,
            "evidence": [
                {
                    "quote": "I attended PyCon.",
                    "message_ids": ["1"],
                    "source_segment_ids": [1],
                    "chunk_kind": "conversation",
                }
            ],
        },
        text="I attended PyCon.",
        subject_display="Alice",
        person_id=1,
        message_id=1,
        source_segment_id=1,
        session_id=1,
    )

    assert "linked_projects" not in event["payload"]
    validate_candidate_payload(
        domain=event["domain"],
        category=event["category"],
        payload=event["payload"],
    )


def test_extract_candidates_from_source_uses_source_chunk_payload(settings, tmp_path):
    source = tmp_path / "alice-note.txt"
    source.write_text("Alice moved to Lisbon in 2024. Alice prefers green tea.", encoding="utf-8")
    ingest = IngestService()
    provider = _RecordingExtractionProvider()
    extraction = ExtractionService(llm_provider=provider)

    with get_connection(settings.db_path) as conn:
        person = FactRepository().upsert_person(
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
            source_type="note",
        )
        candidates = extraction.extract_candidates_from_source(
            conn,
            source_id=imported.source_id,
            person_id=int(person["id"]),
            speaker_label="Alice",
        )

    assert provider.calls
    payload = provider.calls[0]["payload"]
    metadata = provider.calls[0]["metadata"]
    assert payload["message_id"] is None
    assert payload["source_segment_id"] is not None
    assert payload["chunk"]["chunk_kind"] == "source"
    assert payload["chunk"]["messages"] == []
    assert payload["chunk"]["source_segment_ids"] == [payload["source_segment_id"]]
    assert metadata["chunk_kind"] == "source"
    residence = next(candidate for candidate in candidates if candidate["domain"] == "biography")
    assert residence["chunk_kind"] == "source"
    assert residence["evidence"][0]["chunk_kind"] == "source"
    assert residence["evidence"][0]["source_segment_ids"] == payload["chunk"]["source_segment_ids"]


def test_provider_overcaptured_payloads_are_forced_to_review(settings):
    extraction = ExtractionService.from_settings(settings)

    normalized = extraction._normalize_provider_candidate(
        candidate={
            "domain": "biography",
            "category": "residence",
            "subcategory": "",
            "canonical_key": "alice:biography:residence:bad",
            "payload": {"city": "Porto and I prefer coffee"},
            "summary": "Alice lives in Porto and I prefer coffee.",
            "confidence": 0.9,
            "reason": "",
            "needs_review": False,
            "evidence": [{"quote": "I live in Porto and I prefer coffee.", "message_ids": [], "source_segment_ids": [1], "chunk_kind": "conversation"}],
        },
        text="I live in Porto and I prefer coffee.",
        subject_display="Alice",
        person_id=1,
        message_id=1,
        source_segment_id=1,
        session_id=1,
    )

    assert normalized["needs_review"] is True
    assert "suspicious_residence_payload" in normalized["reason"]


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


def test_phase6_schema_docs_and_contracts_include_expanded_taxonomy():
    docs = (Path(__file__).resolve().parents[1] / "docs" / "SCHEMAS.md").read_text()
    assert "age_birth" in docs
    assert "travel_history" in docs
    assert "linked_projects" in docs
    assert "Psychometrics is default-off" in docs

    contract = build_extraction_contract(include_style=True, include_psychometrics=True)
    domains = {item["domain"]: item["categories"] for item in contract["domains"]}
    biography = domains["biography"]
    experiences = domains["experiences"]
    preferences = domains["preferences"]
    social = domains["social_circle"]
    work = domains["work"]

    assert {"age_birth", "health", "values", "finances", "legal", "travel_history", "life_milestone", "communication_preference", "other_stable_self_knowledge"} <= set(biography)
    assert {"location", "intensity", "lesson", "recurrence", "linked_persons", "linked_projects"} <= set(experiences["event"])
    assert {"preference_domain", "valid_from", "valid_to", "original_phrasing", "context"} <= set(preferences["preference"])
    assert {"closeness", "trust", "valence", "aliases", "is_private"} <= set(social["friend"])
    assert {"employment", "engagement", "project"} <= set(work)
    assert {"outcomes", "team", "constraints", "preferences"} <= set(work["employment"] + work["project"])


def test_validate_candidate_payload_accepts_phase6_expanded_shapes():
    examples = [
        ("biography", "age_birth", {"birth_year": "1990"}),
        ("biography", "health", {"health_fact": "gluten sensitivity", "status": "current"}),
        ("biography", "values", {"value": "independence", "context": "career decisions"}),
        ("biography", "finances", {"financial_note": "prefers conservative budgets", "caution": "sensitive"}),
        ("biography", "legal", {"legal_note": "keeps contracts private", "caution": "sensitive"}),
        ("biography", "travel_history", {"location": "Tokyo", "date_range": "2024"}),
        ("biography", "life_milestone", {"milestone": "moved to Lisbon", "event_at": "2024"}),
        ("biography", "communication_preference", {"preference": "short direct updates", "language": "en"}),
        ("biography", "other_stable_self_knowledge", {"fact": "morning person"}),
        (
            "experiences",
            "event",
            {
                "event": "PyCon",
                "location": "Berlin",
                "participants": ["Bob"],
                "valence": "positive",
                "intensity": 0.8,
                "outcome": "won the hackathon",
                "lesson": "ship small demos",
                "recurrence": "annual",
                "linked_persons": ["Bob"],
                "linked_projects": ["Memco"],
            },
        ),
        (
            "preferences",
            "preference",
            {
                "value": "tea",
                "preference_domain": "food",
                "preference_category": "drink",
                "polarity": "like",
                "strength": "medium",
                "is_current": True,
                "valid_from": "2024",
                "original_phrasing": "Tea is my go-to drink.",
                "context": "focus",
            },
        ),
        (
            "social_circle",
            "friend",
            {
                "relation": "friend",
                "target_label": "Bob",
                "target_person_id": 7,
                "is_current": True,
                "closeness": 0.7,
                "trust": 0.8,
                "valence": "positive",
                "aliases": ["Bobby"],
                "is_private": True,
            },
        ),
        (
            "work",
            "engagement",
            {
                "engagement": "Memco launch",
                "role": "builder",
                "org": "FounderOS",
                "status": "active",
                "outcomes": ["private memory API"],
                "team": "solo",
            },
        ),
    ]
    for domain, category, payload in examples:
        assert validate_candidate_payload(domain=domain, category=category, payload=payload) == payload


def test_sample_extraction_fixtures_validate_across_domains():
    candidates = []
    candidates.extend(extract_biography(_context("I'm from Canada. I speak English and Spanish.")))
    candidates.extend(extract_preferences(_context("Tea is my go-to drink when I need to focus.")))
    candidates.extend(extract_social_circle(_context("Bob is my friend.", resolve_person_id=lambda label: 7)))
    candidates.extend(extract_work(_context("I work at OpenAI. I'm a researcher. I use Python.")))
    candidates.extend(extract_experiences(_context("I attended PyCon with Bob in 2024 and it was great.")))
    candidates.extend(extract_psychometrics(_context("I am very curious.")))

    domains = {candidate["domain"] for candidate in candidates}
    assert {"biography", "preferences", "social_circle", "work", "experiences", "psychometrics"} <= domains
    for candidate in candidates:
        validate_candidate_payload(
            domain=candidate["domain"],
            category=candidate["category"],
            payload=candidate["payload"],
        )


def test_psychometrics_remains_default_off_in_orchestrator():
    orchestrator = ExtractionOrchestrator()
    candidates = orchestrator.extract(_context("I am very curious and I prefer tea."))

    assert "psychometrics" not in {candidate["domain"] for candidate in candidates}


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

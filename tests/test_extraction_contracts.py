from __future__ import annotations

import json
from pathlib import Path

import pytest

from memco.config import Settings
from memco.extractors import ExtractionOrchestrator
from memco.extractors.base import (
    ExtractionContext,
    build_extraction_contract,
    build_extraction_system_prompt,
    build_prompt_payload,
    overcaptured_payload_reasons,
    validate_candidate_payload,
)
from memco.extractors.domain_schemas import CANONICAL_LLM_DOMAINS, build_domain_schema
from memco.extractors.llm_structured import build_structured_extraction_prompt
from memco.extractors.text_units import context_for_clause, split_atomic_assertions
from memco.extractors.biography import extract as extract_biography
from memco.extractors.experiences import extract as extract_experiences
from memco.extractors.preferences import extract as extract_preferences
from memco.extractors.psychometrics import extract as extract_psychometrics
from memco.extractors.social_circle import extract as extract_social_circle
from memco.extractors.work import extract as extract_work
from memco.consolidation.biography import BiographyConsolidationPolicy
from memco.db import get_connection
from memco.llm import LLMJSONResponse, LLMTextResponse, LLMUsage
from memco.models.memory_fact import MemoryFactInput
from memco.models.retrieval import RetrievalRequest
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.candidate_service import CandidateService
from memco.services.consolidation_service import ConsolidationService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.services.pipeline_service import IngestPipelineService
from memco.services.publish_service import PublishService
from memco.services.retrieval_service import RetrievalService


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


def test_split_atomic_assertions_keeps_dense_persona_facts_separate() -> None:
    clauses = split_atomic_assertions(
        "My name is Alice. I live in Lisbon. I currently prefer coffee, but I used to prefer tea. "
        "My sister is Maria and my best friend is Tom. "
        "I attended PyCon in May 2024 with Bob and learned to plan rehearsals. "
        "In October 2023, I had a serious car accident during a road trip to the Grand Canyon. "
        "I shipped Project Atlas with Bob on the mobile team. "
        "I work as a designer and use Python and Postgres."
    )

    assert "I live in Lisbon." in clauses
    assert "I currently prefer coffee" in clauses
    assert "I used to prefer tea." in clauses
    assert "My sister is Maria" in clauses
    assert "my best friend is Tom." in clauses
    assert "I attended PyCon in May 2024 with Bob and learned to plan rehearsals." in clauses
    assert "In October 2023, I had a serious car accident during a road trip to the Grand Canyon." in clauses
    assert "I shipped Project Atlas with Bob on the mobile team." in clauses
    assert "I work as a designer" in clauses
    assert "use Python and Postgres." in clauses


def test_context_for_clause_preserves_source_provenance_ids() -> None:
    context = _context("I live in Lisbon. I prefer coffee.")

    clause_context = context_for_clause(context, "I live in Lisbon")

    assert clause_context.text == "I live in Lisbon"
    assert clause_context.subject_key == context.subject_key
    assert clause_context.subject_display == context.subject_display
    assert clause_context.speaker_label == context.speaker_label
    assert clause_context.person_id == context.person_id
    assert clause_context.message_id == 11
    assert clause_context.source_segment_id == 22
    assert clause_context.session_id == 33
    assert clause_context.occurred_at == context.occurred_at


def test_context_for_clause_preserves_resolution_context() -> None:
    conn = object()

    def resolver(label: str) -> int | None:
        return 7 if label == "Bob" else None

    context = ExtractionContext(
        text="My best friend is Bob. I live in Lisbon.",
        subject_key="p1",
        subject_display="Alice",
        speaker_label="Alice",
        person_id=1,
        conn=conn,
        workspace_id=42,
        message_id=11,
        source_segment_id=22,
        session_id=33,
        occurred_at="2026-04-21T10:00:00Z",
        resolve_person_id=resolver,
    )

    clause_context = context_for_clause(context, "My best friend is Bob")

    assert clause_context.conn is conn
    assert clause_context.workspace_id == 42
    assert clause_context.resolve_person_id is resolver
    assert clause_context.resolve_person_id("Bob") == 7


def test_clause_extraction_preserves_published_message_segment_and_chunk_provenance(settings):
    with get_connection(settings.db_path) as conn:
        result = IngestPipelineService().ingest_text(
            settings,
            conn,
            workspace_slug="default",
            text="2026-04-01T10:00:00Z Alice: I live in Lisbon. I currently prefer coffee, but I used to prefer tea.",
            source_type="chat",
            title="clause-provenance",
            person_display_name="Alice",
            person_slug="alice",
            aliases=["Alice"],
            conversation_uid="clause-provenance",
        )

    published = {
        item["candidate"]["canonical_key"]: item
        for item in result["published"]
    }
    residence = next(item for key, item in published.items() if ":biography:residence:" in key)
    preference = next(item for key, item in published.items() if ":preferences:preference:coffee" in key)
    residence_candidate_evidence = residence["candidate"]["evidence"][0]
    preference_candidate_evidence = preference["candidate"]["evidence"][0]
    residence_fact_evidence = residence["fact"]["evidence"][0]
    preference_fact_evidence = preference["fact"]["evidence"][0]

    assert residence_candidate_evidence["quote"] == "I live in Lisbon."
    assert preference_candidate_evidence["quote"] == "I currently prefer coffee"
    assert residence["candidate"]["chunk_id"] == preference["candidate"]["chunk_id"]
    assert residence_candidate_evidence["message_ids"] == preference_candidate_evidence["message_ids"]
    assert residence_candidate_evidence["source_segment_ids"] == preference_candidate_evidence["source_segment_ids"]
    assert residence_candidate_evidence["session_ids"] == preference_candidate_evidence["session_ids"]
    assert residence_fact_evidence["chunk_id"] == preference_fact_evidence["chunk_id"]
    assert residence_fact_evidence["source_segment_id"] == preference_fact_evidence["source_segment_id"]
    assert residence_fact_evidence["session_id"] == preference_fact_evidence["session_id"]


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


class _DomainDenseProvider(_RecordingExtractionProvider):
    def __init__(self, *, fail_domain: str = "") -> None:
        super().__init__()
        self.fail_domain = fail_domain

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict | None = None,
    ) -> LLMJSONResponse:
        payload = json.loads(prompt)
        metadata = metadata or {}
        self.calls.append({"payload": payload, "metadata": metadata})
        domain = str(metadata.get("extraction_domain") or "")
        if domain == self.fail_domain:
            raise RuntimeError(f"{domain} provider failure")
        evidence = [{"quote": payload["text"], "message_ids": [], "source_segment_ids": [], "session_ids": []}]
        items_by_domain = {
            "biography": [
                {
                    "domain": "biography",
                    "category": "residence",
                    "subcategory": "",
                    "canonical_key": f"{payload['subject_key']}:biography:residence:lisbon",
                    "payload": {"city": "Lisbon"},
                    "summary": "Alice lives in Lisbon.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": evidence,
                },
                {
                    "domain": "biography",
                    "category": "family",
                    "subcategory": "sister",
                    "canonical_key": f"{payload['subject_key']}:biography:family:sister:maria",
                    "payload": {"relation": "sister", "name": "Maria"},
                    "summary": "Alice's sister is Maria.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": evidence,
                },
            ],
            "preferences": [
                {
                    "domain": "preferences",
                    "category": "preference",
                    "subcategory": "",
                    "canonical_key": f"{payload['subject_key']}:preferences:preference:coffee",
                    "payload": {"value": "coffee", "polarity": "like", "is_current": True},
                    "summary": "Alice likes coffee.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": evidence,
                }
            ],
            "work": [
                {
                    "domain": "work",
                    "category": "tool",
                    "subcategory": "",
                    "canonical_key": f"{payload['subject_key']}:work:tool:python",
                    "payload": {"tool": "Python"},
                    "summary": "Alice uses Python.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": evidence,
                },
                {
                    "domain": "work",
                    "category": "org",
                    "subcategory": "",
                    "canonical_key": f"{payload['subject_key']}:work:org:acme",
                    "payload": {"org": "Acme", "is_current": True},
                    "summary": "Alice works at Acme.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": evidence,
                },
            ],
            "experiences": [
                {
                    "domain": "experiences",
                    "category": "event",
                    "subcategory": "",
                    "canonical_key": f"{payload['subject_key']}:experiences:event:car-accident",
                    "payload": {"event": "car accident", "summary": "Alice had a car accident.", "event_at": "October", "valence": "negative"},
                    "summary": "Alice had a car accident.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": evidence,
                }
            ],
        }
        if domain == "combined_legacy":
            items = [item for domain_items in items_by_domain.values() for item in domain_items]
        else:
            items = items_by_domain.get(domain, [])
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


def test_phase8_structured_extraction_modules_expose_domain_contracts():
    schema = build_domain_schema(include_psychometrics=True)
    domains = {domain["domain"] for domain in schema["domains"]}
    assert set(CANONICAL_LLM_DOMAINS).issubset(domains)

    prompt = build_structured_extraction_prompt(
        _context("I used to prefer tea, but now I prefer coffee."),
        domain_names=("preferences",),
    )
    assert prompt.schema_name == "memory_fact_candidates"
    assert prompt.payload["extraction_mode"] == "llm_first_structured_extraction"
    assert [domain["domain"] for domain in prompt.payload["output_contract"]["domains"]] == ["preferences"]


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


def test_provider_extraction_runs_domain_scoped_prompts_for_dense_snippet():
    provider = _DomainDenseProvider()
    extraction = ExtractionService(llm_provider=provider)
    dense = (
        "I live in Lisbon. My sister is Maria. I prefer coffee. "
        "I use Python. In October I had a car accident. I work at Acme."
    )

    candidates = extraction.extract_candidates(source_text=dense, person_hint="Alice")

    call_domains = [call["metadata"]["extraction_domain"] for call in provider.calls]
    assert call_domains == ["biography", "preferences", "social_circle", "work", "experiences"]
    for call in provider.calls:
        contract_domains = [item["domain"] for item in call["payload"]["output_contract"]["domains"]]
        assert contract_domains == [call["metadata"]["extraction_domain"]]
    domains = {candidate["domain"] for candidate in candidates}
    assert {"biography", "preferences", "work", "experiences"} <= domains
    assert any(candidate["domain"] == "biography" and candidate["category"] == "family" for candidate in candidates)
    usage_events = extraction.usage_tracker.events
    assert [event.metadata["extraction_domain"] for event in usage_events] == call_domains
    by_domain = extraction.usage_tracker.summary()["production_accounting"]["by_domain"]
    assert by_domain["social_circle"]["operation_count"] == 1
    assert by_domain["social_circle"]["output_tokens"] > 0


def test_provider_combined_legacy_mode_keeps_single_combined_prompt(tmp_path):
    settings = Settings(root=tmp_path / "combined-legacy")
    settings.extraction.mode = "combined_legacy"
    provider = _DomainDenseProvider()
    extraction = ExtractionService(settings=settings, llm_provider=provider)
    dense = (
        "I live in Lisbon. My sister is Maria. I prefer coffee. "
        "I use Python. In October I had a car accident. I work at Acme."
    )

    candidates = extraction.extract_candidates(source_text=dense, person_hint="Alice")

    assert len(provider.calls) == 1
    assert provider.calls[0]["metadata"]["extraction_domain"] == "combined_legacy"
    contract_domains = [item["domain"] for item in provider.calls[0]["payload"]["output_contract"]["domains"]]
    assert {"biography", "preferences", "social_circle", "work", "experiences"} <= set(contract_domains)
    domains = {candidate["domain"] for candidate in candidates}
    assert {"biography", "preferences", "work", "experiences"} <= domains
    usage_events = extraction.usage_tracker.events
    assert len(usage_events) == 1
    assert usage_events[0].metadata["extraction_domain"] == "combined_legacy"
    assert extraction.usage_tracker.summary()["production_accounting"]["by_domain"]["combined_legacy"][
        "operation_count"
    ] == 1


def test_provider_domain_failure_does_not_suppress_other_domains_when_non_strict():
    provider = _DomainDenseProvider(fail_domain="work")
    extraction = ExtractionService(llm_provider=provider)
    dense = (
        "I live in Lisbon. My sister is Maria. I prefer coffee. "
        "I use Python. In October I had a car accident. I work at Acme."
    )

    candidates = extraction._extract_candidates_via_provider(
        text=dense,
        subject_key="alice",
        subject_display="Alice",
        speaker_label="Alice",
        person_id=None,
        conn=None,
        workspace_id=None,
        strict_validation=False,
    )

    domains = {candidate["domain"] for candidate in candidates}
    assert {"biography", "preferences", "experiences"} <= domains
    assert "work" not in domains
    assert [call["metadata"]["extraction_domain"] for call in provider.calls] == [
        "biography",
        "preferences",
        "social_circle",
        "work",
        "experiences",
    ]


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


def test_pdf_source_extraction_publish_and_retrieve_preserves_page_locator_and_source_type(settings):
    source_repo = SourceRepository()
    candidate_repo = CandidateRepository()
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
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/pdf/alice.pdf",
            source_type="pdf",
            origin_uri="/tmp/alice.pdf",
            title="alice",
            sha256="pdf-source-extraction",
            parsed_text="## Page 2\n\nAlice moved to Lisbon in 2024.",
        )
        source_repo.replace_chunks(
            conn,
            source_id=source_id,
            parsed_text="## Page 2\n\nAlice moved to Lisbon in 2024.",
            segments=[
                {
                    "segment_type": "pdf_page",
                    "segment_index": 1,
                    "section_title": "Page 2",
                    "text": "## Page 2\n\nAlice moved to Lisbon in 2024.",
                    "locator": {"page_number": 2, "page_label": "Page 2", "section_title": "Page 2"},
                }
            ],
        )
        extracted = extraction.extract_candidates_from_source(
            conn,
            source_id=source_id,
            person_id=int(person["id"]),
            speaker_label="Alice",
        )
        assert extracted
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind=extracted[0]["chunk_kind"],
            chunk_id=int(extracted[0]["chunk_id"]),
            domain=extracted[0]["domain"],
            category=extracted[0]["category"],
            subcategory=extracted[0]["subcategory"],
            canonical_key=extracted[0]["canonical_key"],
            payload=extracted[0]["payload"],
            summary=extracted[0]["summary"],
            confidence=float(extracted[0]["confidence"]),
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=extracted[0]["evidence"],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="validated_candidate",
        )
        published = PublishService().publish_candidate(conn, workspace_slug="default", candidate_id=int(candidate["id"]))
        retrieved = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )

    candidate_evidence = extracted[0]["evidence"][0]
    assert candidate_evidence["source_type"] == "pdf"
    assert candidate_evidence["source_segment_ids"]
    fact_evidence = published["fact"]["evidence"][0]
    assert fact_evidence["quote_text"] == "## Page 2\n\nAlice moved to Lisbon in 2024."
    assert fact_evidence["locator_json"]["source_type"] == "pdf"
    assert fact_evidence["locator_json"]["source_segment_type"] == "pdf_page"
    assert fact_evidence["locator_json"]["source_segment_locator"]["page_number"] == 2
    retrieved_evidence = retrieved.hits[0].evidence[0]
    assert retrieved_evidence["source_segment_id"] == fact_evidence["source_segment_id"]
    assert retrieved_evidence["locator_json"]["source_type"] == "pdf"
    assert retrieved_evidence["locator_json"]["source_segment_locator"]["page_label"] == "Page 2"


def test_markdown_source_extraction_publish_and_retrieve_preserves_section_locator(settings, tmp_path):
    candidate_repo = CandidateRepository()
    provider = _RecordingExtractionProvider()
    extraction = ExtractionService(llm_provider=provider)
    source = tmp_path / "alice-journal.md"
    source.write_text(
        "\n".join(
            [
                "---",
                "title: Alice Journal",
                "date: 2026-04-24",
                "---",
                "",
                "# 2026-04-24",
                "",
                "Alice moved to Lisbon in 2024.",
            ]
        ),
        encoding="utf-8",
    )

    with get_connection(settings.db_path) as conn:
        person = FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="markdown",
        )
        extracted = extraction.extract_candidates_from_source(
            conn,
            source_id=imported.source_id,
            person_id=int(person["id"]),
            speaker_label="Alice",
        )
        assert extracted
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=imported.source_id,
            conversation_id=None,
            chunk_kind=extracted[0]["chunk_kind"],
            chunk_id=int(extracted[0]["chunk_id"]),
            domain=extracted[0]["domain"],
            category=extracted[0]["category"],
            subcategory=extracted[0]["subcategory"],
            canonical_key=extracted[0]["canonical_key"],
            payload=extracted[0]["payload"],
            summary=extracted[0]["summary"],
            confidence=float(extracted[0]["confidence"]),
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=extracted[0]["evidence"],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="validated_candidate",
        )
        published = PublishService().publish_candidate(conn, workspace_slug="default", candidate_id=int(candidate["id"]))
        retrieved = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )

    candidate_evidence = extracted[0]["evidence"][0]
    assert candidate_evidence["source_segment_ids"]
    fact_evidence = published["fact"]["evidence"][0]
    assert fact_evidence["quote_text"].startswith("# 2026-04-24")
    assert fact_evidence["locator_json"]["source_type"] == "markdown"
    assert fact_evidence["locator_json"]["source_segment_type"] == "markdown_section"
    assert fact_evidence["locator_json"]["source_segment_locator"]["heading"] == "2026-04-24"
    assert fact_evidence["locator_json"]["source_segment_locator"]["date"] == "2026-04-24"
    assert isinstance(fact_evidence["locator_json"]["source_segment_locator"]["char_start"], int)
    retrieved_evidence = retrieved.hits[0].evidence[0]
    assert retrieved_evidence["source_segment_id"] == fact_evidence["source_segment_id"]
    assert retrieved_evidence["locator_json"]["source_type"] == "markdown"
    assert retrieved_evidence["locator_json"]["source_segment_locator"]["heading"] == "2026-04-24"


def test_inline_note_extraction_publish_and_retrieve_preserves_note_locator(settings):
    candidate_repo = CandidateRepository()
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
        imported = IngestService().import_text(
            settings,
            conn,
            workspace_slug="default",
            text="Alice moved to Lisbon in 2024.",
            title="Alice Seed",
            source_type="note",
        )
        extracted = extraction.extract_candidates_from_source(
            conn,
            source_id=imported.source_id,
            person_id=int(person["id"]),
            speaker_label="Alice",
        )
        assert extracted
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=imported.source_id,
            conversation_id=None,
            chunk_kind=extracted[0]["chunk_kind"],
            chunk_id=int(extracted[0]["chunk_id"]),
            domain=extracted[0]["domain"],
            category=extracted[0]["category"],
            subcategory=extracted[0]["subcategory"],
            canonical_key=extracted[0]["canonical_key"],
            payload=extracted[0]["payload"],
            summary=extracted[0]["summary"],
            confidence=float(extracted[0]["confidence"]),
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=extracted[0]["evidence"],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="validated_candidate",
        )
        published = PublishService().publish_candidate(conn, workspace_slug="default", candidate_id=int(candidate["id"]))
        retrieved = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )

    candidate_evidence = extracted[0]["evidence"][0]
    assert candidate_evidence["source_type"] == "note"
    assert candidate_evidence["source_segment_ids"]
    fact_evidence = published["fact"]["evidence"][0]
    assert fact_evidence["quote_text"] == "Alice moved to Lisbon in 2024."
    assert fact_evidence["locator_json"]["source_type"] == "note"
    assert fact_evidence["locator_json"]["source_segment_type"] == "inline_note"
    assert fact_evidence["locator_json"]["source_segment_locator"]["origin_uri"] == "inline://alice-seed"
    assert fact_evidence["locator_json"]["source_segment_locator"]["char_start"] == 0
    assert fact_evidence["locator_json"]["source_segment_locator"]["char_end"] == len("Alice moved to Lisbon in 2024.")
    retrieved_evidence = retrieved.hits[0].evidence[0]
    assert retrieved_evidence["source_segment_id"] == fact_evidence["source_segment_id"]
    assert retrieved_evidence["locator_json"]["source_type"] == "note"
    assert retrieved_evidence["locator_json"]["source_segment_locator"]["origin_uri"] == "inline://alice-seed"


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
    assert overcaptured_payload_reasons({"role": "designer and use Python"}) == ["overcaptured_role"]
    assert "overcaptured_city" in normalized["reason"]
    assert "suspicious_residence_payload" in normalized["reason"]


def test_provider_overcaptured_atomic_fields_are_not_publishable(settings):
    extraction = ExtractionService.from_settings(settings)

    for field in ("name", "city", "role", "title", "tool", "value", "event", "org"):
        for marker_text in (
            "alpha and I prefer coffee",
            "alpha and use Python",
            "alpha and work with Postgres",
            "alpha; beta",
            "alpha. Beta",
        ):
            assert overcaptured_payload_reasons({field: marker_text}) == [f"overcaptured_{field}"]

    normalized = extraction._normalize_provider_candidate(
        candidate={
            "domain": "work",
            "category": "employment",
            "subcategory": "",
            "canonical_key": "alice:work:employment:bad",
            "payload": {"role": "designer and use Python", "title": "designer and use Python"},
            "summary": "Alice works as designer and use Python.",
            "confidence": 0.9,
            "reason": "",
            "needs_review": False,
            "evidence": [{"quote": "I work as a designer and use Python.", "message_ids": [], "source_segment_ids": [1], "chunk_kind": "conversation"}],
        },
        text="I work as a designer and use Python.",
        subject_display="Alice",
        person_id=1,
        message_id=1,
        source_segment_id=1,
        session_id=1,
    )

    assert normalized["needs_review"] is True
    assert "overcaptured_role" in normalized["reason"]
    assert "overcaptured_title" in normalized["reason"]


def test_provider_residence_without_residence_source_marker_is_not_publishable(settings):
    extraction = ExtractionService.from_settings(settings)

    normalized = extraction._normalize_provider_candidate(
        candidate={
            "domain": "biography",
            "category": "residence",
            "subcategory": "",
            "canonical_key": "alice:biography:residence:tea",
            "payload": {"city": "tea"},
            "summary": "Alice lives in tea.",
            "confidence": 0.9,
            "reason": "",
            "needs_review": False,
            "evidence": [{"quote": "I like tea.", "message_ids": [], "source_segment_ids": [1], "chunk_kind": "conversation"}],
        },
        text="I like tea.",
        subject_display="Alice",
        person_id=1,
        message_id=1,
        source_segment_id=1,
        session_id=1,
    )

    assert normalized["needs_review"] is True
    assert "source_mismatch_residence" in normalized["reason"]


def test_provider_residence_with_residence_source_marker_remains_publishable(settings):
    extraction = ExtractionService.from_settings(settings)

    for source_text in ("I live in Lisbon.", "Alice lives in Lisbon."):
        normalized = extraction._normalize_provider_candidate(
            candidate={
                "domain": "biography",
                "category": "residence",
                "subcategory": "",
                "canonical_key": "alice:biography:residence:lisbon",
                "payload": {"city": "Lisbon"},
                "summary": "Alice lives in Lisbon.",
                "confidence": 0.9,
                "reason": "",
                "needs_review": False,
                "evidence": [{"quote": source_text, "message_ids": [], "source_segment_ids": [1], "chunk_kind": "conversation"}],
            },
            text=source_text,
            subject_display="Alice",
            person_id=1,
            message_id=1,
            source_segment_id=1,
            session_id=1,
        )

        assert normalized["needs_review"] is False
        assert "source_mismatch_residence" not in normalized.get("reason", "")


def test_provider_residence_for_different_source_subject_is_not_publishable(settings):
    extraction = ExtractionService.from_settings(settings)

    normalized = extraction._normalize_provider_candidate(
        candidate={
            "domain": "biography",
            "category": "residence",
            "subcategory": "",
            "canonical_key": "alice:biography:residence:berlin",
            "payload": {"city": "Berlin"},
            "summary": "Alice lives in Berlin.",
            "confidence": 0.9,
            "reason": "",
            "needs_review": False,
            "evidence": [{"quote": "Bob lives in Berlin.", "message_ids": [], "source_segment_ids": [1], "chunk_kind": "conversation"}],
        },
        text="Bob lives in Berlin.",
        subject_display="Alice",
        person_id=1,
        message_id=1,
        source_segment_id=1,
        session_id=1,
    )

    assert normalized["needs_review"] is True
    assert "source_mismatch_residence" in normalized["reason"]


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
    assert payload["use_in_generation"] is False
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


def test_psychometrics_generation_hint_requires_multiple_evidence_signals():
    candidates = extract_psychometrics(_context("I'm very curious."))

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["extracted_signal"]["explicit_self_description"] is True
    assert payload["extracted_signal"]["evidence_count"] == 1
    assert payload["use_in_generation"] is False


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


BIOGRAPHY_CATEGORY_EXAMPLES = [
    ("residence", _context("I live in Lisbon."), {"city": "Lisbon"}),
    ("origin", _context("I'm from Canada."), {"place": "Canada"}),
    ("identity", _context("My name is Alice Example."), {"name": "Alice Example"}),
    ("education", _context("I studied computer science at MIT."), {"field": "computer science", "institution": "MIT"}),
    ("family", _context("My sister is Emma."), {"relation": "sister", "name": "Emma"}),
    ("pets", _context("My dog is Bruno."), {"pet_type": "dog", "pet_name": "Bruno"}),
    ("age_birth", _context("I was born in 1990."), {"birth_year": "1990"}),
    ("health", _context("I have asthma."), {"health_fact": "asthma", "status": "current"}),
    ("languages", _context("I speak English and Spanish."), {"languages": ["English", "Spanish"]}),
    ("habits", _context("I usually wake up at 6am."), {"habit": "wake up at 6am"}),
    ("goals", _context("My goal is to run a marathon."), {"goal": "run a marathon"}),
    ("constraints", _context("I must avoid gluten."), {"constraint": "gluten"}),
    ("values", _context("I value independence in career decisions."), {"value": "independence", "context": "career decisions"}),
    ("finances", _context("I keep an emergency fund for six months."), {"financial_note": "an emergency fund for six months", "caution": "sensitive"}),
    ("legal", _context("I keep contracts private."), {"legal_note": "contracts private", "caution": "sensitive"}),
    ("travel_history", _context("I traveled to Tokyo in 2024."), {"location": "Tokyo", "event_at": "2024", "date_range": "2024"}),
    ("life_milestone", _context("I got married in 2021."), {"milestone": "got married", "event_at": "2021"}),
    (
        "communication_preference",
        _context("Please send me short direct updates in English."),
        {"preference": "short direct updates", "language": "English", "context": "communication"},
    ),
    (
        "other_stable_self_knowledge",
        _context("My passport is in the blue travel pouch."),
        {"fact": "passport is in the blue travel pouch", "context": "private note"},
    ),
]


@pytest.mark.parametrize("category,context,expected_payload", BIOGRAPHY_CATEGORY_EXAMPLES)
def test_biography_extractor_covers_all_categories_with_evidence(category, context, expected_payload):
    candidates = extract_biography(context)
    candidate = next(item for item in candidates if item["category"] == category)

    assert candidate["payload"] == expected_payload
    assert candidate["domain"] == "biography"
    assert candidate["evidence"][0]["quote"] == context.text
    assert candidate["evidence"][0]["message_ids"] == [str(context.message_id)]
    assert candidate["evidence"][0]["source_segment_ids"] == [context.source_segment_id]
    assert validate_candidate_payload(domain="biography", category=category, payload=candidate["payload"]) == expected_payload


BIOGRAPHY_NEGATED_EXAMPLES = [
    ("residence", "I do not live in Lisbon."),
    ("origin", "I'm not from Canada."),
    ("identity", "My name is not Alice Example."),
    ("education", "I did not study computer science at MIT."),
    ("family", "My sister is not Emma."),
    ("pets", "My dog is not Bruno."),
    ("age_birth", "I was not born in 1990."),
    ("health", "I do not have asthma."),
    ("languages", "I do not speak Spanish."),
    ("habits", "I do not usually wake up at 6am."),
    ("goals", "My goal is not to run a marathon."),
    ("constraints", "I do not have a gluten constraint."),
    ("values", "I do not value independence in career decisions."),
    ("finances", "I do not keep an emergency fund for six months."),
    ("legal", "I do not keep contracts private."),
    ("travel_history", "I did not travel to Tokyo in 2024."),
    ("life_milestone", "I did not get married in 2021."),
    ("communication_preference", "I do not prefer short direct updates in English."),
    ("other_stable_self_knowledge", "My passport is not in the blue travel pouch."),
]


BIOGRAPHY_HYPOTHETICAL_EXAMPLES = [
    ("residence", "If I live in Lisbon, I will update you."),
    ("origin", "If I'm from Canada, this note is wrong."),
    ("identity", "If my name is Alice Example, use that label."),
    ("education", "If I studied computer science at MIT, add it later."),
    ("family", "If my sister is Emma, invite her."),
    ("pets", "If my dog is Bruno, call the vet."),
    ("age_birth", "If I was born in 1990, check the record."),
    ("health", "If I have asthma, remind me about inhalers."),
    ("languages", "If I speak English and Spanish, translate it."),
    ("habits", "If I usually wake up at 6am, schedule breakfast."),
    ("goals", "If my goal is to run a marathon, make a plan."),
    ("constraints", "If I can't eat gluten, choose another restaurant."),
    ("values", "If I value independence in career decisions, remind me."),
    ("finances", "If I keep an emergency fund for six months, tag it."),
    ("legal", "If I keep contracts private, encrypt the note."),
    ("travel_history", "If I traveled to Tokyo in 2024, add it."),
    ("life_milestone", "If I got married in 2021, note it."),
    ("communication_preference", "If I prefer short direct updates in English, use them."),
    ("other_stable_self_knowledge", "If my passport is in the blue travel pouch, remind me."),
]


@pytest.mark.parametrize("category,text", BIOGRAPHY_NEGATED_EXAMPLES)
def test_biography_extractor_skips_negated_positive_facts(category, text):
    candidates = extract_biography(_context(text))

    assert all(candidate["category"] != category for candidate in candidates)


@pytest.mark.parametrize("category,text", BIOGRAPHY_HYPOTHETICAL_EXAMPLES)
def test_biography_extractor_skips_hypothetical_positive_facts(category, text):
    candidates = extract_biography(_context(text))

    assert all(candidate["category"] != category for candidate in candidates)


def test_biography_prompt_contract_includes_domain_specific_examples():
    contract = build_extraction_contract(include_style=False, include_psychometrics=False)
    biography = next(item for item in contract["domains"] if item["domain"] == "biography")

    assert any("I was born in 1990" in item["text"] for item in biography["examples"])
    assert any("no current residence fact" in item["extract"] for item in biography["examples"])
    assert any("communication_preference" in item["extract"] for item in biography["examples"])


def test_biography_consolidation_marks_residence_as_current_state_update():
    policy = BiographyConsolidationPolicy()

    assert "residence" in policy.current_state_categories
    assert "travel_history" not in policy.current_state_categories
    assert policy.semantic_duplicate_key(category="residence", payload={"city": "Lisbon"}) == "residence:lisbon"
    assert "lisbon" in policy.semantic_duplicate_key(category="travel_history", payload={"location": "Lisbon", "event_at": "2024"})


def test_biography_residence_update_supersedes_previous_active_fact(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/biography-residence-update.md",
            source_type="note",
            origin_uri="/tmp/biography-residence-update.md",
            title="biography-residence-update",
            sha256="biography-residence-update-sha",
            parsed_text="Alice lived in Berlin and later moved to Lisbon.",
        )
        berlin = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Alice lives in Berlin.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lived in Berlin.",
            ),
        )
        lisbon = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Alice lives in Lisbon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice moved to Lisbon.",
            ),
        )
        berlin = fact_repo.get_fact(conn, fact_id=int(berlin["id"]))
        lisbon = fact_repo.get_fact(conn, fact_id=int(lisbon["id"]))

    assert berlin["status"] == "superseded"
    assert berlin["superseded_by_fact_id"] == lisbon["id"]
    assert lisbon["status"] == "active"
    assert lisbon["supersedes_fact_id"] == berlin["id"]


def test_preferences_extractor_tracks_polarity_strength_and_reason():
    candidates = extract_preferences(_context("I strongly dislike coffee because it makes me anxious."))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["payload"]["value"] == "coffee"
    assert candidate["payload"]["polarity"] == "dislike"
    assert candidate["payload"]["strength"] == "strong"
    assert candidate["payload"]["reason"] == "it makes me anxious"
    assert candidate["payload"]["preference_domain"] == "food_drink"
    assert candidate["payload"]["preference_category"] == "drink"
    assert candidate["payload"]["original_phrasing"] == "I strongly dislike coffee because it makes me anxious"
    assert candidate["evidence"][0]["quote"] == "I strongly dislike coffee because it makes me anxious."
    assert validate_candidate_payload(domain="preferences", category="preference", payload=candidate["payload"]) == candidate["payload"]


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

    current = [candidate for candidate in candidates if candidate["payload"]["is_current"] is True]
    past = [candidate for candidate in candidates if candidate["payload"]["is_current"] is False]
    assert [candidate["payload"]["value"] for candidate in current] == ["coffee"]
    assert [candidate["payload"]["value"] for candidate in past] == ["tea"]
    assert past[0]["payload"]["valid_to"] == "now"


def test_preferences_extractor_handles_current_preference_with_past_update():
    candidates = extract_preferences(_context("I prefer coffee, but I used to prefer tea."))

    current = [candidate for candidate in candidates if candidate["payload"]["is_current"] is True]
    past = [candidate for candidate in candidates if candidate["payload"]["is_current"] is False]
    assert [candidate["payload"]["value"] for candidate in current] == ["coffee"]
    assert [candidate["payload"]["value"] for candidate in past] == ["tea"]
    assert current[0]["payload"]["temporal_status"] == "current"
    assert past[0]["payload"]["temporal_status"] == "past"
    assert past[0]["payload"]["valid_to"] == "now"


def test_preferences_extractor_extracts_currently_and_past_in_same_sentence():
    candidates = extract_preferences(_context("I currently prefer coffee, but I used to prefer tea."))

    values = {candidate["payload"]["value"]: candidate["payload"] for candidate in candidates}
    assert values["coffee"]["is_current"] is True
    assert values["coffee"]["temporal_status"] == "current"
    assert values["tea"]["is_current"] is False
    assert values["tea"]["temporal_status"] == "past"
    assert values["tea"]["valid_to"] == "now"


def test_preferences_extractor_captures_required_schema_fields_for_evolution():
    candidates = extract_preferences(_context("I used to prefer tea, but now I prefer coffee."))
    by_value = {candidate["payload"]["value"]: candidate for candidate in candidates}

    assert set(by_value) == {"tea", "coffee"}
    assert by_value["coffee"]["payload"] == {
        "value": "coffee",
        "preference_domain": "food_drink",
        "preference_category": "drink",
        "polarity": "like",
        "strength": "medium",
        "reason": "",
        "is_current": True,
        "temporal_status": "current",
        "valid_from": "",
        "valid_to": "",
        "original_phrasing": "I prefer coffee",
        "context": "",
    }
    assert by_value["tea"]["payload"] == {
        "value": "tea",
        "preference_domain": "food_drink",
        "preference_category": "drink",
        "polarity": "like",
        "strength": "medium",
        "reason": "",
        "is_current": False,
        "temporal_status": "past",
        "valid_from": "",
        "valid_to": "now",
        "original_phrasing": "I used to prefer tea, but now I prefer coffee",
        "context": "",
    }


def test_preferences_extractor_supports_indirect_go_to_phrase():
    candidates = extract_preferences(_context("Tea is my go-to drink when I need to focus."))

    assert len(candidates) == 1
    assert candidates[0]["payload"]["value"] == "Tea"
    assert candidates[0]["payload"]["polarity"] == "like"
    assert candidates[0]["payload"]["preference_domain"] == "food_drink"
    assert candidates[0]["payload"]["preference_category"] == "drink"
    assert candidates[0]["payload"]["context"] == "I need to focus"


def test_work_extractor_splits_role_and_tools_in_same_sentence():
    candidates = extract_work(_context("I work as a designer and use Python and Postgres."))

    roles = [candidate for candidate in candidates if candidate["category"] == "employment"]
    tools = [candidate["payload"]["tool"] for candidate in candidates if candidate["category"] == "tool"]
    assert roles[0]["payload"]["role"] == "designer"
    assert set(tools) == {"Python", "Postgres"}


def test_work_extractor_handles_atomized_bare_use_clause():
    candidates = extract_work(_context("use Python and Postgres."))

    tools = [candidate["payload"]["tool"] for candidate in candidates if candidate["category"] == "tool"]
    assert set(tools) == {"Python", "Postgres"}


def test_experience_extractor_captures_pause_outcome_after_accident():
    candidates = extract_experiences(
        _context("In October 2023, I had a serious car accident during a road trip to the Grand Canyon and I paused hiking for two months.")
    )

    assert len(candidates) == 1
    assert candidates[0]["payload"]["location"] == "Grand Canyon"
    assert candidates[0]["payload"]["outcome"] == "paused hiking for two months"


def test_experience_extractor_captures_embedded_lesson():
    candidates = extract_experiences(_context("I attended PyCon in May 2024 with Bob and learned to plan rehearsals."))

    assert len(candidates) == 1
    assert candidates[0]["payload"]["event"] == "PyCon"
    assert candidates[0]["payload"]["lesson"] == "plan rehearsals"


def test_preferences_extractor_skips_hypothetical_preferences():
    assert extract_preferences(_context("If I prefer tea later, I will tell you.")) == []


def test_preferences_prompt_contract_includes_evolution_examples():
    contract = build_extraction_contract(include_style=False, include_psychometrics=False)
    preferences = next(item for item in contract["domains"] if item["domain"] == "preferences")

    assert any("used to prefer tea" in item["text"] for item in preferences["examples"])
    assert any("is_current=false" in item["extract"] for item in preferences["examples"])
    assert any("no preference fact" in item["extract"] for item in preferences["examples"])


def test_social_circle_extractor_captures_current_flag_and_relationship_event():
    contexts = [
        _context("Bob is my friend.", resolve_person_id=lambda label: 7),
        _context("My manager is Priya."),
        _context("Jordan is my client."),
        _context("My acquaintance is Lee."),
        _context("Alice used to be my manager."),
    ]

    candidates = [candidate for context in contexts for candidate in extract_social_circle(context)]
    friend = next(candidate for candidate in candidates if candidate["category"] == "friend")
    current_manager = next(candidate for candidate in candidates if candidate["category"] == "manager" and candidate["payload"]["is_current"])
    client = next(candidate for candidate in candidates if candidate["category"] == "client")
    acquaintance = next(candidate for candidate in candidates if candidate["category"] == "acquaintance")
    past_manager = next(candidate for candidate in candidates if candidate["category"] == "manager" and not candidate["payload"]["is_current"])

    assert friend["payload"]["target_person_id"] == 7
    assert friend["payload"]["is_current"] is True
    assert current_manager["payload"]["target_label"] == "Priya"
    assert client["payload"]["target_label"] == "Jordan"
    assert acquaintance["payload"]["target_label"] == "Lee"
    assert past_manager["payload"]["is_current"] is False
    assert past_manager["payload"]["target_label"] == "Alice"


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


def test_work_extractor_splits_tool_lists_into_separate_candidates():
    candidates = extract_work(_context("I use Python and Postgres."))
    comma_candidates = extract_work(_context("I work with Docker, Kubernetes, and Terraform."))

    tools = [candidate["payload"]["tool"] for candidate in candidates if candidate["category"] == "tool"]
    assert tools == ["Python", "Postgres"]
    comma_tools = [candidate["payload"]["tool"] for candidate in comma_candidates if candidate["category"] == "tool"]
    assert comma_tools == ["Docker", "Kubernetes", "Terraform"]


def test_work_extractor_covers_launched_and_worked_on_projects():
    launched = extract_work(_context("I launched Project Phoenix in March."))
    worked_on = extract_work(_context("I worked on Project Atlas."))
    worked_on_and_launched = extract_work(_context("I worked on Project Phoenix and launched it in March."))

    assert any(candidate["category"] == "project" and candidate["payload"]["project"] == "Project Phoenix in March" for candidate in launched)
    assert any(candidate["category"] == "project" and candidate["payload"]["project"] == "Project Atlas" for candidate in worked_on)
    combined_project = next(candidate for candidate in worked_on_and_launched if candidate["category"] == "project")
    combined_text = f"{combined_project['payload']['project']} {combined_project['evidence'][0]['quote']}"
    assert "Project Phoenix" in combined_text
    assert "March" in combined_text


def test_work_extractor_covers_employment_team_dates_and_status():
    candidates = extract_work(_context("I work as a staff engineer at OpenAI with the Applied team since 2022."))
    employment = next(candidate for candidate in candidates if candidate["category"] == "employment")

    assert employment["payload"] == {
        "title": "staff engineer",
        "role": "staff engineer",
        "is_current": True,
        "org": "OpenAI",
        "status": "current",
        "start_date": "2022",
        "team": "Applied",
    }
    assert validate_candidate_payload(domain="work", category="employment", payload=employment["payload"]) == employment["payload"]


def test_work_extractor_covers_engagement_client_role_and_dates():
    candidates = extract_work(_context("I consult for Acme as a platform advisor since 2024."))
    engagement = next(candidate for candidate in candidates if candidate["category"] == "engagement")

    assert engagement["payload"] == {
        "engagement": "consulting",
        "client": "Acme",
        "status": "current",
        "role": "platform advisor",
        "start_date": "2024",
    }
    assert validate_candidate_payload(domain="work", category="engagement", payload=engagement["payload"]) == engagement["payload"]


def test_work_extractor_covers_project_client_team_outcomes_and_status():
    candidates = extract_work(
        _context("I shipped Project Atlas for Acme with Bob on the mobile team. The outcome was 20% faster onboarding.")
    )
    project = next(candidate for candidate in candidates if candidate["category"] == "project")

    assert project["payload"] == {
        "project": "Project Atlas",
        "status": "completed",
        "team": "mobile",
        "client": "Acme",
        "outcomes": ["20% faster onboarding"],
        "collaborators": ["Bob"],
    }
    assert validate_candidate_payload(domain="work", category="project", payload=project["payload"]) == project["payload"]


def test_work_prompt_contract_includes_complete_category_examples():
    contract = build_extraction_contract(include_style=False, include_psychometrics=False)
    work = next(item for item in contract["domains"] if item["domain"] == "work")

    assert any("staff engineer" in item["text"] for item in work["examples"])
    assert any("engagement=consulting" in item["extract"] for item in work["examples"])
    assert any("outcomes=" in item["extract"] for item in work["examples"])
    assert {"outcomes", "tasks", "collaborators"} <= set(work["categories"]["project"])


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


def test_experiences_extractor_captures_accident_with_temporal_location_valence_and_outcome():
    candidates = extract_experiences(
        _context(
            "In October 2023, I had a serious car accident during a family road trip to the Grand Canyon. "
            "It was scary and I had to pause pottery."
        )
    )

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert "car accident" in payload["event"]
    assert payload["event_at"] == "October 2023"
    assert payload["temporal_anchor"] == "October 2023"
    assert payload["event_type"] == "accident"
    assert payload["location"] == "Grand Canyon"
    assert payload["valence"] == "negative"
    assert payload["intensity"] >= 0.8
    assert payload["salience"] == payload["intensity"]
    assert payload["outcome"] == "pause pottery"
    assert payload["lesson"] == ""
    assert payload["linked_persons"] == []
    assert payload["linked_projects"] == []


def test_experiences_extractor_captures_hierarchy_linked_people_projects_and_lesson():
    candidates = extract_experiences(
        _context(
            "In March 2024, I attended launch week with Bob and Dana during Project Phoenix. "
            "We won the beta award and I learned to plan rehearsals."
        )
    )

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["event"] == "launch week"
    assert payload["event_at"] == "March 2024"
    assert payload["participants"] == ["Bob", "Dana"]
    assert payload["linked_persons"] == ["Bob", "Dana"]
    assert payload["linked_projects"] == ["Project Phoenix"]
    assert payload["event_hierarchy"] == ["Project Phoenix", "launch week"]
    assert payload["outcome"] == "won the beta award and I learned to plan rehearsals"
    assert payload["lesson"] == "plan rehearsals"
    assert validate_candidate_payload(domain="experiences", category="event", payload=payload) == payload


def test_experiences_extractor_captures_recurrence_and_date_range():
    candidates = extract_experiences(_context("Every summer I went to PyCon with Bob from 2021 to 2023."))

    assert len(candidates) == 1
    payload = candidates[0]["payload"]
    assert payload["event"] == "PyCon"
    assert payload["date_range"] == "2021 to 2023"
    assert payload["temporal_anchor"] == "2021 to 2023"
    assert payload["recurrence"] == "every summer"
    assert payload["linked_persons"] == ["Bob"]


def test_experiences_prompt_contract_includes_hierarchy_examples():
    contract = build_extraction_contract(include_style=False, include_psychometrics=False)
    experiences = next(item for item in contract["domains"] if item["domain"] == "experiences")

    assert any("Project Phoenix" in item["text"] for item in experiences["examples"])
    assert any("linked_projects" in item["extract"] for item in experiences["examples"])
    assert any("recurrence=every summer" in item["extract"] for item in experiences["examples"])


def test_experiences_extractor_cleans_month_year_from_event_text():
    promoted = extract_experiences(_context("I got promoted in March 2024."))
    suffered = extract_experiences(_context("I suffered a car accident in October 2023."))
    attended_may = extract_experiences(_context("In May 2024, I attended PyCon with Bob."))

    assert promoted[0]["payload"]["event"] == "promoted"
    assert promoted[0]["payload"]["event_at"] == "March 2024"
    assert suffered[0]["payload"]["event"] == "car accident"
    assert suffered[0]["payload"]["event_at"] == "October 2023"
    assert attended_may[0]["payload"]["event"] == "PyCon"
    assert attended_may[0]["payload"]["event_at"] == "May 2024"


def test_experiences_extractor_captures_dated_move_without_simple_move_duplication():
    dated = extract_experiences(_context("I moved to Lisbon in October 2023."))
    undated = extract_experiences(_context("I moved to Lisbon."))

    assert dated[0]["payload"]["event"] == "moved to Lisbon"
    assert dated[0]["payload"]["event_at"] == "October 2023"
    assert undated == []


def test_experiences_extractor_captures_breakup_as_event():
    candidates = extract_experiences(_context("I broke up with Taylor in 2022."))

    assert candidates[0]["payload"]["event"] == "broke up with Taylor"
    assert candidates[0]["payload"]["event_at"] == "2022"


@pytest.mark.parametrize(
    "text",
    [
        "I did not have a car accident.",
        "I had no car accident in 2024.",
        "I might have a car accident someday.",
        "I may attend PyCon someday.",
    ],
)
def test_experiences_extractor_skips_negated_or_hypothetical_events(text):
    assert extract_experiences(_context(text)) == []


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


def test_experiences_extractor_uses_temporal_anchor_for_relative_months():
    candidates = extract_experiences(_context("Last October I had a car accident."))

    assert len(candidates) == 1
    assert candidates[0]["payload"]["event"] == "car accident"
    assert candidates[0]["payload"]["event_at"] == ""
    assert candidates[0]["payload"]["temporal_anchor"] == "Last October"


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
    assert {"event_type", "location", "intensity", "salience", "lesson", "recurrence", "linked_persons", "linked_projects"} <= set(experiences["event"])
    assert {"preference_domain", "valid_from", "valid_to", "original_phrasing", "context"} <= set(preferences["preference"])
    assert {"closeness", "trust", "valence", "aliases", "is_private"} <= set(social["friend"])
    assert {"best_friend", "manager", "client", "acquaintance"} <= set(social)
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


def test_validate_candidate_payload_rejects_single_signal_generation_flag():
    payload = {
        "framework": "big_five",
        "trait": "openness",
        "extracted_signal": {
            "signal_kind": "explicit_self_description",
            "explicit_self_description": True,
            "signal_confidence": 0.72,
            "evidence_count": 1,
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

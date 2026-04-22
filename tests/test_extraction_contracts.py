from __future__ import annotations

import json

from memco.db import get_connection
from memco.repositories.fact_repository import FactRepository
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService


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
    extraction = ExtractionService()
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
    extraction = ExtractionService()
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

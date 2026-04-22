from __future__ import annotations

import json

from memco.db import get_connection
from memco.repositories.fact_repository import FactRepository
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.ingest_service import IngestService


def test_import_json_conversation_creates_conversation_messages_and_chunks(settings, tmp_path):
    source = tmp_path / "conversation.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I live in Berlin."},
                    {"speaker": "Bob", "timestamp": "2026-04-21T10:01:00Z", "text": "I prefer tea."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:02:00Z", "text": "My cat is Luna."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingest = IngestService()
    conversation_service = ConversationIngestService()
    with get_connection(settings.db_path) as conn:
        imported = ingest.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
            conversation_uid="main",
            title="JSON Conversation",
        )
        message_count = conn.execute(
            "SELECT COUNT(*) AS count FROM conversation_messages WHERE conversation_id = ?",
            (result.conversation_id,),
        ).fetchone()
        chunk_count = conn.execute(
            "SELECT COUNT(*) AS count FROM conversation_chunks WHERE conversation_id = ?",
            (result.conversation_id,),
        ).fetchone()
        segment_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM source_segments
            WHERE conversation_id = ? AND segment_type = 'message'
            """,
            (result.conversation_id,),
        ).fetchone()
    assert result.message_count == 3
    assert message_count["count"] == 3
    assert result.chunk_count >= 1
    assert chunk_count["count"] == result.chunk_count
    assert segment_count["count"] == result.message_count


def test_plaintext_conversation_resolution_maps_known_alias(settings, tmp_path):
    source = tmp_path / "conversation.txt"
    source.write_text(
        "Alice: I like coffee.\nA. Example: I moved to Lisbon.\nUnknown: hello\n",
        encoding="utf-8",
    )
    ingest = IngestService()
    conversation_service = ConversationIngestService()
    fact_repo = FactRepository()
    with get_connection(settings.db_path) as conn:
        fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice Example",
            slug="alice-example",
            person_type="human",
            aliases=["Alice", "A. Example"],
        )
        imported = ingest.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="text",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
            conversation_uid="main",
            title="Plain Conversation",
        )
        rows = conn.execute(
            """
            SELECT speaker_label, speaker_person_id
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()
    assert rows[0]["speaker_person_id"] is not None
    assert rows[1]["speaker_person_id"] is not None
    assert rows[2]["speaker_person_id"] is None
    assert result.unresolved_speakers == ["Unknown"]


def test_conversation_speaker_manual_resolution_updates_mapping(settings, tmp_path):
    source = tmp_path / "conversation-resolve.txt"
    source.write_text(
        "Guest: I moved to Lisbon.\n",
        encoding="utf-8",
    )
    ingest = IngestService()
    conversation_service = ConversationIngestService()
    fact_repo = FactRepository()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Guest User",
            slug="guest-user",
            person_type="human",
            aliases=["Guest User"],
        )
        imported = ingest.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="text",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
            conversation_uid="main",
            title="Resolvable Conversation",
        )
        mapping = conversation_service.resolve_speaker(
            conn,
            workspace_slug="default",
            conversation_id=result.conversation_id,
            speaker_key="guest",
            person_id=int(person["id"]),
        )
        rows = conn.execute(
            """
            SELECT speaker_person_id
            FROM conversation_messages
            WHERE conversation_id = ?
            """,
            (result.conversation_id,),
        ).fetchall()

    assert mapping["person_id"] == int(person["id"])
    assert mapping["resolution_method"] == "manual_override"
    assert rows[0]["speaker_person_id"] == int(person["id"])

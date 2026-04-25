from __future__ import annotations

import json
import mailbox

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
    assert result.session_count == 1
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


def test_plaintext_conversation_resolution_maps_cyrillic_alias(settings, tmp_path):
    source = tmp_path / "conversation-ru.txt"
    source.write_text(
        "Алиса: Я люблю coffee.\nГость: привет\n",
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
            aliases=["Алиса"],
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
            title="Russian Conversation",
        )
        rows = conn.execute(
            """
            SELECT speaker_label, speaker_person_id, text
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()

    assert rows[0]["speaker_label"] == "Алиса"
    assert rows[0]["speaker_person_id"] is not None
    assert "Я люблю coffee." in rows[0]["text"]
    assert rows[1]["speaker_person_id"] is None
    assert result.unresolved_speakers == ["Гость"]


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


def test_import_json_conversation_preserves_explicit_session_boundaries(settings, tmp_path):
    source = tmp_path / "conversation-sessions.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T10:00:00Z",
                        "text": "I live in Berlin.",
                        "session_uid": "morning",
                    },
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T10:05:00Z",
                        "text": "I like tea.",
                        "session_uid": "morning",
                    },
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T18:00:00Z",
                        "text": "I moved to Lisbon.",
                        "session_uid": "evening",
                    },
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
        )
        sessions = conn.execute(
            "SELECT id, session_index, session_uid, detection_method FROM sessions WHERE conversation_id = ? ORDER BY session_index ASC",
            (result.conversation_id,),
        ).fetchall()
        message_sessions = conn.execute(
            "SELECT message_index, session_id FROM conversation_messages WHERE conversation_id = ? ORDER BY message_index ASC",
            (result.conversation_id,),
        ).fetchall()
        chunk_sessions = conn.execute(
            "SELECT chunk_index, session_id, start_message_index, end_message_index FROM conversation_chunks WHERE conversation_id = ? ORDER BY chunk_index ASC",
            (result.conversation_id,),
        ).fetchall()

    assert result.session_count == 2
    assert [row["detection_method"] for row in sessions] == ["explicit", "explicit"]
    first_session_id = int(sessions[0]["id"])
    second_session_id = int(sessions[1]["id"])
    assert [int(row["session_id"]) for row in message_sessions] == [first_session_id, first_session_id, second_session_id]
    assert [int(row["session_id"]) for row in chunk_sessions] == [first_session_id, second_session_id]
    assert [(row["start_message_index"], row["end_message_index"]) for row in chunk_sessions] == [(0, 1), (2, 2)]


def test_import_json_conversation_splits_sessions_on_time_gap(settings, tmp_path):
    settings.ingest.session_gap_minutes = 60
    source = tmp_path / "conversation-gap.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I live in Berlin."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:10:00Z", "text": "I like tea."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T12:30:00Z", "text": "I moved to Lisbon."},
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
        )
        sessions = conn.execute(
            "SELECT session_index, detection_method, started_at, ended_at FROM sessions WHERE conversation_id = ? ORDER BY session_index ASC",
            (result.conversation_id,),
        ).fetchall()

    assert result.session_count == 2
    assert [row["detection_method"] for row in sessions] == ["single", "gap"]
    assert sessions[0]["started_at"] == "2026-04-21T10:00:00Z"
    assert sessions[0]["ended_at"] == "2026-04-21T10:10:00Z"
    assert sessions[1]["started_at"] == "2026-04-21T12:30:00Z"


def test_conversation_chunking_uses_token_budget_and_overlap(settings, tmp_path):
    settings.ingest.max_tokens_per_chunk = 6
    settings.ingest.overlap_tokens = 3
    source = tmp_path / "conversation-token-overlap.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"text": "alpha beta gamma"},
                    {"text": "delta epsilon zeta"},
                    {"text": "eta theta iota"},
                    {"text": "kappa lambda mu"},
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
        )
        chunks = conn.execute(
            """
            SELECT chunk_index, start_message_index, end_message_index, token_count, locator_json
            FROM conversation_chunks
            WHERE conversation_id = ?
            ORDER BY chunk_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()

    assert result.chunk_count == 3
    locators = [json.loads(row["locator_json"]) for row in chunks]
    assert [(row["start_message_index"], row["end_message_index"]) for row in chunks] == [(0, 1), (1, 2), (2, 3)]
    assert [row["token_count"] for row in chunks] == [6, 6, 6]
    assert locators[0]["overlap_message_indexes"] == []
    assert locators[1]["overlap_message_indexes"] == [1]
    assert locators[2]["overlap_message_indexes"] == [2]
    assert all(locator["token_budget"] == 6 for locator in locators)
    assert all(locator["overlap_tokens"] == 3 for locator in locators)


def test_conversation_chunking_preserves_session_boundaries_with_overlap(settings, tmp_path):
    settings.ingest.max_tokens_per_chunk = 6
    settings.ingest.overlap_tokens = 3
    source = tmp_path / "conversation-token-sessions.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"text": "alpha beta gamma", "session_uid": "morning"},
                    {"text": "delta epsilon zeta", "session_uid": "morning"},
                    {"text": "eta theta iota", "session_uid": "morning"},
                    {"text": "kappa lambda mu", "session_uid": "evening"},
                    {"text": "nu xi omicron", "session_uid": "evening"},
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
        )
        chunk_rows = conn.execute(
            """
            SELECT chunk_index, session_id, start_message_index, end_message_index, locator_json
            FROM conversation_chunks
            WHERE conversation_id = ?
            ORDER BY chunk_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()
        sessions = conn.execute(
            "SELECT id, session_uid FROM sessions WHERE conversation_id = ? ORDER BY session_index ASC",
            (result.conversation_id,),
        ).fetchall()

    first_session_id = int(sessions[0]["id"])
    second_session_id = int(sessions[1]["id"])
    locators = [json.loads(row["locator_json"]) for row in chunk_rows]

    assert [(row["session_id"], row["start_message_index"], row["end_message_index"]) for row in chunk_rows] == [
        (first_session_id, 0, 1),
        (first_session_id, 1, 2),
        (second_session_id, 3, 4),
    ]
    assert locators[1]["overlap_message_indexes"] == [1]
    assert locators[2]["overlap_message_indexes"] == []
    assert [locator["session_uid"] for locator in locators] == ["session-0001", "session-0001", "session-0002"]


def test_conversation_chunking_rejects_single_message_over_token_budget(settings, tmp_path):
    settings.ingest.max_tokens_per_chunk = 6
    settings.ingest.overlap_tokens = 3
    source = tmp_path / "conversation-oversized-message.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"text": "one two three four five six seven"},
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
        try:
            conversation_service.import_conversation(
                settings,
                conn,
                workspace_slug="default",
                source_id=imported.source_id,
            )
        except ValueError as exc:
            assert "exceeds max_tokens_per_chunk" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected oversized message to be rejected")


def test_email_import_conversation_uses_parser_messages_not_header_lines(settings, tmp_path):
    source = tmp_path / "conversation.eml"
    source.write_text(
        "\n".join(
            [
                "From: Alice <alice@example.com>",
                "To: Bob <bob@example.com>",
                "Subject: Weekend plan",
                "Date: Tue, 21 Apr 2026 10:00:00 +0000",
                "Content-Type: text/plain; charset=utf-8",
                "",
                "Let's meet for coffee on Friday.",
            ]
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
            source_type="email",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        row = conn.execute(
            """
            SELECT speaker_label, occurred_at, text
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_index ASC
            """,
            (result.conversation_id,),
        ).fetchone()

    assert result.message_count == 1
    assert row is not None
    assert row["speaker_label"] == "Alice <alice@example.com>"
    assert "coffee on Friday" in row["text"]
    assert "Subject:" not in row["text"]


def test_whatsapp_import_conversation_uses_structured_parser_messages(settings, tmp_path):
    source = tmp_path / "whatsapp.txt"
    source.write_text(
        "\n".join(
            [
                "[12/01/2024, 09:15:12] Alice: Hello Bob",
                "multiline note",
                "12/01/24, 09:16 - Alice: Work: I moved to Lisbon.",
                "12.01.2024, 09:17 - Bob: <Media omitted>",
                "12.01.2024, 09:18 - Messages and calls are end-to-end encrypted.",
            ]
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
            source_type="whatsapp",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        rows = conn.execute(
            """
            SELECT speaker_label, occurred_at, text
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()

    assert result.message_count == 2
    assert rows[0]["speaker_label"] == "Alice"
    assert rows[0]["occurred_at"] == "2024-01-12T09:15:12Z"
    assert rows[0]["text"] == "Hello Bob\nmultiline note"
    assert rows[1]["speaker_label"] == "Alice: Work"
    assert rows[1]["text"] == "I moved to Lisbon."


def test_telegram_import_conversation_preserves_json_reply_metadata(settings, tmp_path):
    source = tmp_path / "telegram.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "id": 10,
                        "type": "message",
                        "date": "2024-01-12T09:15:12",
                        "from": "Alice",
                        "text": ["Hello ", {"type": "bold", "text": "Bob"}],
                    },
                    {
                        "id": 11,
                        "type": "message",
                        "date": "2024-01-12T09:16:12",
                        "from": "Bob",
                        "reply_to_message_id": 10,
                        "text": "Reply received",
                    },
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
            source_type="telegram",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        rows = conn.execute(
            """
            SELECT speaker_label, occurred_at, text, meta_json
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()

    assert result.message_count == 2
    assert rows[0]["speaker_label"] == "Alice"
    assert rows[0]["text"] == "Hello Bob"
    assert rows[1]["speaker_label"] == "Bob"
    assert rows[1]["occurred_at"] == "2024-01-12T09:16:12Z"
    assert json.loads(rows[1]["meta_json"])["reply_to_message_id"] == 10


def test_mbox_import_conversation_preserves_thread_messages(settings, tmp_path):
    source = tmp_path / "thread.mbox"
    box = mailbox.mbox(str(source), create=True)
    box.lock()
    try:
        first = mailbox.mboxMessage()
        first.set_from("alice@example.com")
        first["From"] = "Alice <alice@example.com>"
        first["To"] = "Bob <bob@example.com>"
        first["Subject"] = "Weekend plan"
        first["Date"] = "Tue, 21 Apr 2026 10:00:00 +0000"
        first.set_payload("Let's meet on Friday.")
        box.add(first)

        second = mailbox.mboxMessage()
        second.set_from("bob@example.com")
        second["From"] = "Bob <bob@example.com>"
        second["To"] = "Alice <alice@example.com>"
        second["Subject"] = "Re: Weekend plan"
        second["Date"] = "Tue, 21 Apr 2026 11:00:00 +0000"
        second.set_payload("Friday works for me.")
        box.add(second)
        box.flush()
    finally:
        box.unlock()
        box.close()

    ingest = IngestService()
    conversation_service = ConversationIngestService()
    with get_connection(settings.db_path) as conn:
        imported = ingest.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="email",
        )
        result = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        rows = conn.execute(
            """
            SELECT speaker_label, text
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_index ASC
            """,
            (result.conversation_id,),
        ).fetchall()

    assert result.message_count == 2
    assert [row["speaker_label"] for row in rows] == ["Alice <alice@example.com>", "Bob <bob@example.com>"]
    assert "Let's meet on Friday." in rows[0]["text"]
    assert "Friday works for me." in rows[1]["text"]

from __future__ import annotations

import json

from memco.utils import isoformat_z


class ConversationRepository:
    def ensure_workspace(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace: {slug}")
        return int(row["id"])

    def upsert_conversation(
        self,
        conn,
        *,
        workspace_slug: str,
        source_id: int,
        conversation_uid: str,
        title: str,
        started_at: str,
        ended_at: str,
    ) -> int:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO conversations (
                workspace_id, source_id, conversation_uid, title, started_at, ended_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, conversation_uid) DO UPDATE SET
                title = excluded.title,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                updated_at = excluded.updated_at
            """,
            (workspace_id, source_id, conversation_uid, title, started_at, ended_at, now, now),
        )
        row = conn.execute(
            "SELECT id FROM conversations WHERE source_id = ? AND conversation_uid = ?",
            (source_id, conversation_uid),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert conversation")
        return int(row["id"])

    def replace_messages(self, conn, *, conversation_id: int, messages: list[dict]) -> None:
        conversation_row = conn.execute(
            "SELECT source_id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if conversation_row is None:
            raise ValueError("Unknown conversation")
        source_id = int(conversation_row["source_id"])
        existing = conn.execute(
            "SELECT id FROM conversation_chunks WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        for row in existing:
            conn.execute("DELETE FROM conversation_chunk_fts WHERE rowid = ?", (int(row["id"]),))
        conn.execute("DELETE FROM conversation_chunks WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM source_segments WHERE conversation_id = ? AND segment_type = 'message'", (conversation_id,))
        conn.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (conversation_id,))
        now = isoformat_z()
        for index, message in enumerate(messages):
            cursor = conn.execute(
                """
                INSERT INTO conversation_messages (
                    conversation_id, message_index, role, speaker_label, speaker_key,
                    speaker_person_id, occurred_at, text, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    index,
                    message.get("role", "unknown"),
                    message.get("speaker_label", ""),
                    message.get("speaker_key", ""),
                    message.get("speaker_person_id"),
                    message.get("occurred_at", ""),
                    message.get("text", ""),
                    json.dumps(message.get("meta", {}), ensure_ascii=False),
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO source_segments (
                    source_id, segment_type, segment_index, chunk_id, conversation_id, message_id,
                    text, locator_json, occurred_at, created_at
                ) VALUES (?, 'message', ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    index,
                    conversation_id,
                    message_id,
                    message.get("text", ""),
                    json.dumps({"message_index": index, "speaker_key": message.get("speaker_key", "")}, ensure_ascii=False),
                    message.get("occurred_at", ""),
                    now,
                ),
            )

    def upsert_speaker_map(self, conn, *, conversation_id: int, mappings: list[dict]) -> None:
        now = isoformat_z()
        for mapping in mappings:
            conn.execute(
                """
                INSERT INTO conversation_speaker_map (
                    conversation_id, speaker_key, raw_label, person_id, resolution_method,
                    confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id, speaker_key) DO UPDATE SET
                    raw_label = excluded.raw_label,
                    person_id = excluded.person_id,
                    resolution_method = excluded.resolution_method,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (
                    conversation_id,
                    mapping["speaker_key"],
                    mapping.get("raw_label", ""),
                    mapping.get("person_id"),
                    mapping.get("resolution_method", "unresolved"),
                    mapping.get("confidence", 0.0),
                    now,
                    now,
                ),
            )

    def list_speaker_map(self, conn, *, conversation_id: int) -> list[dict]:
        rows = conn.execute(
            """
            SELECT speaker_key, raw_label, person_id, resolution_method, confidence
            FROM conversation_speaker_map
            WHERE conversation_id = ?
            ORDER BY speaker_key ASC
            """,
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def resolve_speaker(
        self,
        conn,
        *,
        conversation_id: int,
        speaker_key: str,
        person_id: int,
        raw_label: str = "",
        resolution_method: str = "manual_override",
        confidence: float = 1.0,
    ) -> dict:
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO conversation_speaker_map (
                conversation_id, speaker_key, raw_label, person_id, resolution_method,
                confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, speaker_key) DO UPDATE SET
                raw_label = CASE WHEN excluded.raw_label != '' THEN excluded.raw_label ELSE conversation_speaker_map.raw_label END,
                person_id = excluded.person_id,
                resolution_method = excluded.resolution_method,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                speaker_key,
                raw_label,
                person_id,
                resolution_method,
                confidence,
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE conversation_messages
            SET speaker_person_id = ?
            WHERE conversation_id = ? AND speaker_key = ?
            """,
            (person_id, conversation_id, speaker_key),
        )
        row = conn.execute(
            """
            SELECT speaker_key, raw_label, person_id, resolution_method, confidence
            FROM conversation_speaker_map
            WHERE conversation_id = ? AND speaker_key = ?
            """,
            (conversation_id, speaker_key),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to resolve speaker")
        return dict(row)

    def replace_chunks(self, conn, *, conversation_id: int, source_id: int, chunks: list[dict]) -> None:
        existing = conn.execute(
            "SELECT id FROM conversation_chunks WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        for row in existing:
            conn.execute("DELETE FROM conversation_chunk_fts WHERE rowid = ?", (int(row["id"]),))
        conn.execute("DELETE FROM conversation_chunks WHERE conversation_id = ?", (conversation_id,))
        now = isoformat_z()
        for index, chunk in enumerate(chunks):
            cursor = conn.execute(
                """
                INSERT INTO conversation_chunks (
                    conversation_id, source_id, chunk_index, start_message_index, end_message_index,
                    text, token_count, locator_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    source_id,
                    index,
                    chunk["start_message_index"],
                    chunk["end_message_index"],
                    chunk["text"],
                    chunk["token_count"],
                    json.dumps(chunk.get("locator", {}), ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO conversation_chunk_fts(rowid, text) VALUES (?, ?)",
                (int(cursor.lastrowid), chunk["text"]),
            )

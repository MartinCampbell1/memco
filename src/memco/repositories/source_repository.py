from __future__ import annotations

import json
from pathlib import Path

from memco.db import get_connection
from memco.utils import chunk_text, isoformat_z, json_dumps


class SourceRepository:
    def ensure_workspace(self, conn, slug: str) -> int:
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO workspaces (slug, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                updated_at = excluded.updated_at
            """,
            (slug, slug.replace("-", " ").title(), now, now),
        )
        row = conn.execute(
            "SELECT id FROM workspaces WHERE slug = ?",
            (slug,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Failed to ensure workspace {slug}")
        return int(row["id"])

    def record_source(
        self,
        conn,
        *,
        workspace_slug: str,
        source_path: str,
        source_type: str,
        origin_uri: str,
        title: str,
        sha256: str,
        parsed_text: str,
        meta: dict | None = None,
        status: str = "ready",
    ) -> int:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO sources (
                workspace_id, source_path, source_type, origin_uri, title, sha256,
                imported_at, parsed_text, meta_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, source_path, sha256) DO UPDATE SET
                title = excluded.title,
                parsed_text = excluded.parsed_text,
                meta_json = excluded.meta_json,
                status = excluded.status
            """,
            (
                workspace_id,
                source_path,
                source_type,
                origin_uri,
                title,
                sha256,
                now,
                parsed_text,
                json_dumps(meta or {}),
                status,
            ),
        )
        row = conn.execute(
            "SELECT id FROM sources WHERE workspace_id = ? AND source_path = ? AND sha256 = ?",
            (workspace_id, source_path, sha256),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to record source")
        return int(row["id"])

    def replace_chunks(self, conn, *, source_id: int, parsed_text: str, section_title: str = "") -> None:
        existing = conn.execute(
            "SELECT id FROM source_chunks WHERE source_id = ?",
            (source_id,),
        ).fetchall()
        for row in existing:
            conn.execute("DELETE FROM source_chunk_fts WHERE rowid = ?", (int(row["id"]),))
        conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
        conn.execute(
            "DELETE FROM source_segments WHERE source_id = ? AND segment_type = 'source_chunk'",
            (source_id,),
        )
        now = isoformat_z()
        for index, piece in enumerate(chunk_text(parsed_text), start=0):
            cursor = conn.execute(
                """
                INSERT INTO source_chunks (source_id, chunk_index, text, token_count, section_title, locator_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source_id, index, piece, max(1, len(piece.split())), section_title, "{}"),
            )
            conn.execute(
                "INSERT INTO source_chunk_fts(rowid, text, section_title) VALUES (?, ?, ?)",
                (int(cursor.lastrowid), piece, section_title),
            )
            conn.execute(
                """
                INSERT INTO source_segments (
                    source_id, segment_type, segment_index, chunk_id, conversation_id, message_id,
                    text, locator_json, occurred_at, created_at
                ) VALUES (?, 'source_chunk', ?, ?, NULL, NULL, ?, ?, '', ?)
                """,
                (
                    source_id,
                    index,
                    int(cursor.lastrowid),
                    piece,
                    "{}",
                    now,
                ),
            )

    def get_source(self, conn, *, source_id: int):
        return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    def get_segment_by_chunk_id(self, conn, *, chunk_id: int) -> dict | None:
        row = conn.execute(
            """
            SELECT *
            FROM source_segments
            WHERE chunk_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chunk_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_segment_by_message_id(self, conn, *, message_id: int) -> dict | None:
        row = conn.execute(
            """
            SELECT *
            FROM source_segments
            WHERE message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (message_id,),
        ).fetchone()
        return dict(row) if row is not None else None

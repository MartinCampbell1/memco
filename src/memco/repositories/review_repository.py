from __future__ import annotations

import json

from memco.utils import isoformat_z


class ReviewRepository:
    def ensure_workspace(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace: {slug}")
        return int(row["id"])

    def enqueue(self, conn, *, workspace_slug: str, person_id: int | None, candidate: dict, reason: str, candidate_id: int | None = None) -> int:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        cursor = conn.execute(
            """
            INSERT INTO review_queue (workspace_id, person_id, candidate_id, candidate_json, status, reason, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (workspace_id, person_id, candidate_id, json.dumps(candidate, ensure_ascii=False), reason, isoformat_z()),
        )
        return int(cursor.lastrowid)

    def list_items(
        self,
        conn,
        *,
        workspace_slug: str,
        status: str | None = None,
        person_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = "SELECT * FROM review_queue WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        if person_id is not None:
            sql += " AND person_id = ?"
            params.append(person_id)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        items: list[dict] = []
        for row in rows:
            payload = dict(row)
            payload["candidate"] = json.loads(payload.pop("candidate_json") or "{}")
            items.append(payload)
        return items

    def list_items_for_candidates(
        self,
        conn,
        *,
        workspace_slug: str,
        candidate_ids: list[int],
        status: str | None = None,
    ) -> list[dict]:
        if not candidate_ids:
            return []
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        placeholders = ",".join("?" for _ in candidate_ids)
        sql = f"SELECT * FROM review_queue WHERE workspace_id = ? AND candidate_id IN ({placeholders})"
        params: list[object] = [workspace_id, *candidate_ids]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id DESC"
        rows = conn.execute(sql, params).fetchall()
        items: list[dict] = []
        for row in rows:
            payload = dict(row)
            payload["candidate"] = json.loads(payload.pop("candidate_json") or "{}")
            items.append(payload)
        return items

    def resolve(self, conn, *, queue_id: int, decision: str, reason: str = "") -> dict:
        now = isoformat_z()
        conn.execute(
            """
            UPDATE review_queue
            SET status = ?, reason = CASE WHEN ? != '' THEN ? ELSE reason END, resolved_at = ?
            WHERE id = ?
            """,
            (decision, reason, reason, now, queue_id),
        )
        row = conn.execute("SELECT * FROM review_queue WHERE id = ?", (queue_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown review queue item")
        payload = dict(row)
        payload["candidate"] = json.loads(payload.pop("candidate_json") or "{}")
        return payload

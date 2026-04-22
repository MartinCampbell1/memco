from __future__ import annotations

import json

from memco.utils import isoformat_z


class RetrievalLogRepository:
    def ensure_workspace(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace: {slug}")
        return int(row["id"])

    def create_log(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None,
        route_name: str,
        query_hash: str,
        query_length: int,
        domain_filter: str,
        fact_hit_count: int,
        fallback_hit_count: int,
        unsupported_premise_detected: bool,
        fact_ids: list[int],
        fallback_refs: list[dict],
        latency_ms: int,
    ) -> dict:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        cursor = conn.execute(
            """
            INSERT INTO retrieval_logs (
                workspace_id, person_id, route_name, query_hash, query_length, domain_filter,
                fact_hit_count, fallback_hit_count, unsupported_premise_detected,
                fact_ids_json, fallback_refs_json, latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                person_id,
                route_name,
                query_hash,
                query_length,
                domain_filter,
                fact_hit_count,
                fallback_hit_count,
                1 if unsupported_premise_detected else 0,
                json.dumps(fact_ids, ensure_ascii=False),
                json.dumps(fallback_refs, ensure_ascii=False),
                latency_ms,
                isoformat_z(),
            ),
        )
        return self.get_log(conn, log_id=int(cursor.lastrowid))

    def get_log(self, conn, *, log_id: int) -> dict:
        row = conn.execute("SELECT * FROM retrieval_logs WHERE id = ?", (log_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown retrieval log")
        item = dict(row)
        item["fact_ids"] = json.loads(item.pop("fact_ids_json") or "[]")
        item["fallback_refs"] = json.loads(item.pop("fallback_refs_json") or "[]")
        item["unsupported_premise_detected"] = bool(item["unsupported_premise_detected"])
        return item

    def list_logs(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        route_name: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = "SELECT id FROM retrieval_logs WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if person_id is not None:
            sql += " AND person_id = ?"
            params.append(person_id)
        if route_name:
            sql += " AND route_name = ?"
            params.append(route_name)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [self.get_log(conn, log_id=int(row["id"])) for row in rows]

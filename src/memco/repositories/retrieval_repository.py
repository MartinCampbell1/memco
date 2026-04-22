from __future__ import annotations

import json
import re


SEARCH_TERM_RE = re.compile(r"[^\W_]+", re.UNICODE)


class RetrievalRepository:
    def ensure_workspace(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace: {slug}")
        return int(row["id"])

    def retrieve_facts(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        query: str,
        domain: str | None = None,
        category: str | None = None,
        temporal_mode: str = "auto",
        limit: int = 8,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = """
            SELECT *
            FROM memory_facts
            WHERE workspace_id = ? AND person_id = ?
        """
        params: list[object] = [workspace_id, person_id]
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if temporal_mode == "current":
            sql += " AND status = 'active'"
        elif temporal_mode == "history":
            sql += " AND status IN ('active', 'superseded')"
        else:
            sql += " AND status = 'active'"
        sql += " ORDER BY confidence DESC, observed_at DESC, id DESC LIMIT ?"
        params.append(limit * 4)
        rows = conn.execute(sql, params).fetchall()
        terms = [term.lower() for term in SEARCH_TERM_RE.findall(query)]
        hits: list[dict] = []
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json") or "{}")
            haystack = " ".join(
                [
                    item.get("domain", ""),
                    item.get("category", ""),
                    item.get("subcategory", ""),
                    item.get("canonical_key", ""),
                    item.get("summary", ""),
                    json.dumps(payload, ensure_ascii=False),
                ]
            ).lower()
            score = float(item.get("confidence", 0.0))
            for term in terms:
                if term in haystack:
                    score += 1.0
            if terms and score <= float(item.get("confidence", 0.0)):
                continue
            evidence_rows = conn.execute(
                """
                SELECT source_id, chunk_id, source_segment_id, quote_text, support_type, source_confidence
                FROM memory_evidence
                WHERE fact_id = ?
                ORDER BY id ASC
                """,
                (int(item["id"]),),
            ).fetchall()
            hits.append(
                {
                    "fact_id": int(item["id"]),
                    "domain": item["domain"],
                    "category": item["category"],
                    "summary": item["summary"],
                    "confidence": float(item["confidence"]),
                    "score": score,
                    "status": item["status"],
                    "source_kind": item["source_kind"],
                    "observed_at": item["observed_at"],
                    "valid_from": item["valid_from"],
                    "valid_to": item["valid_to"],
                    "payload": payload,
                    "evidence": [dict(evidence) for evidence in evidence_rows],
                }
            )
        hits.sort(key=lambda hit: (-hit["score"], -hit["confidence"], hit["fact_id"]))
        return hits[:limit]

    def retrieve_fallback_chunks(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        terms = [term.lower() for term in SEARCH_TERM_RE.findall(query)]
        if not terms:
            return []
        rows = conn.execute(
            """
            SELECT
              cc.id AS chunk_id,
              cc.source_id,
              cc.text,
              cm.speaker_person_id AS person_id
            FROM conversation_chunks cc
            JOIN conversations c ON c.id = cc.conversation_id
            LEFT JOIN conversation_messages cm
              ON cm.conversation_id = c.id
             AND cm.message_index = cc.start_message_index
            WHERE c.workspace_id = ?
            ORDER BY cc.id DESC
            """,
            (workspace_id,),
        ).fetchall()
        hits: list[dict] = []
        for row in rows:
            item = dict(row)
            if item.get("person_id") != person_id:
                continue
            haystack = (item.get("text") or "").lower()
            score = 0.0
            for term in terms:
                if term in haystack:
                    score += 1.0
            if score <= 0:
                continue
            hits.append(
                {
                    "source_id": int(item["source_id"]),
                    "chunk_kind": "conversation",
                    "chunk_id": int(item["chunk_id"]),
                    "text": item.get("text") or "",
                    "score": score,
                }
            )
        hits.sort(key=lambda hit: (-hit["score"], -hit["chunk_id"]))
        return hits[:limit]

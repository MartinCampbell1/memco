from __future__ import annotations

import json

from memco.extractors.base import validate_candidate_payload
from memco.utils import isoformat_z


ALLOWED_DOMAINS = {"biography", "preferences", "social_circle", "work", "experiences", "psychometrics", "style"}
ALLOWED_CANDIDATE_STATUSES = {
    "extracted_candidate",
    "validated_candidate",
    "needs_review",
    "published",
    "rejected",
}

ALLOWED_CANDIDATE_TRANSITIONS = {
    "extracted_candidate": {"validated_candidate", "needs_review", "rejected"},
    "validated_candidate": {"validated_candidate", "published", "rejected", "needs_review"},
    "needs_review": {"validated_candidate", "needs_review", "rejected"},
    "published": {"published"},
    "rejected": {"rejected"},
}


class CandidateRepository:
    def ensure_workspace(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace: {slug}")
        return int(row["id"])

    def add_candidate(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None,
        source_id: int,
        conversation_id: int | None,
        session_id: int | None = None,
        chunk_kind: str,
        chunk_id: int | None,
        domain: str,
        category: str,
        subcategory: str,
        canonical_key: str,
        payload: dict,
        summary: str,
        confidence: float,
        reason: str = "",
        extracted_at: str | None = None,
    ) -> dict:
        if domain not in ALLOWED_DOMAINS:
            raise ValueError(f"Unsupported candidate domain: {domain}")
        validate_candidate_payload(domain=domain, category=category, payload=payload)
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        existing = conn.execute(
            """
            SELECT id
            FROM fact_candidates
            WHERE workspace_id = ?
              AND source_id = ?
              AND COALESCE(chunk_id, -1) = COALESCE(?, -1)
              AND canonical_key = ?
              AND candidate_status != 'rejected'
            ORDER BY id DESC
            LIMIT 1
            """,
            (workspace_id, source_id, chunk_id, canonical_key),
        ).fetchone()
        if existing is not None:
            return self.get_candidate(conn, candidate_id=int(existing["id"]))
        now = isoformat_z()
        candidate_extracted_at = extracted_at or now
        cursor = conn.execute(
            """
            INSERT INTO fact_candidates (
                workspace_id, person_id, source_id, conversation_id, session_id, chunk_kind, chunk_id,
                domain, category, subcategory, canonical_key, payload_json, summary,
                confidence, candidate_status, publish_target_fact_id, dedupe_key, reason, evidence_json,
                extracted_at, reviewed_at, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted_candidate', NULL, ?, ?, '[]', ?, '', '', ?, ?)
            """,
            (
                workspace_id,
                person_id,
                source_id,
                conversation_id,
                session_id,
                chunk_kind,
                chunk_id,
                domain,
                category,
                subcategory,
                canonical_key,
                json.dumps(payload, ensure_ascii=False),
                summary,
                confidence,
                canonical_key,
                reason,
                candidate_extracted_at,
                now,
                now,
            ),
        )
        return self.get_candidate(conn, candidate_id=int(cursor.lastrowid))

    def get_candidate(self, conn, *, candidate_id: int) -> dict:
        row = conn.execute(
            "SELECT * FROM fact_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Unknown candidate")
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        evidence_json = item.pop("evidence_json", "[]") if "evidence_json" in item else "[]"
        item["evidence"] = json.loads(evidence_json or "[]")
        return item

    def list_candidates(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        candidate_status: str | None = None,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = "SELECT * FROM fact_candidates WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if person_id is not None:
            sql += " AND person_id = ?"
            params.append(person_id)
        if candidate_status:
            sql += " AND candidate_status = ?"
            params.append(candidate_status)
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        sql += " ORDER BY extracted_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            evidence_json = item.pop("evidence_json", "[]") if "evidence_json" in item else "[]"
            item["evidence"] = json.loads(evidence_json or "[]")
            results.append(item)
        return results

    def mark_candidate_status(
        self,
        conn,
        *,
        candidate_id: int,
        candidate_status: str,
        publish_target_fact_id: int | None = None,
        reason: str = "",
    ) -> dict:
        if candidate_status not in ALLOWED_CANDIDATE_STATUSES:
            raise ValueError(f"Unsupported candidate status: {candidate_status}")
        current = self.get_candidate(conn, candidate_id=candidate_id)
        current_status = current["candidate_status"]
        allowed = ALLOWED_CANDIDATE_TRANSITIONS.get(current_status, set())
        if candidate_status not in allowed:
            raise ValueError(f"Cannot transition candidate from {current_status} to {candidate_status}")
        now = isoformat_z()
        conn.execute(
            """
            UPDATE fact_candidates
            SET candidate_status = ?,
                publish_target_fact_id = ?,
                reason = CASE WHEN ? != '' THEN ? ELSE reason END,
                reviewed_at = ?,
                published_at = CASE WHEN ? = 'published' THEN ? ELSE published_at END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                candidate_status,
                publish_target_fact_id,
                reason,
                reason,
                now,
                candidate_status,
                now,
                now,
                candidate_id,
            ),
        )
        return self.get_candidate(conn, candidate_id=candidate_id)

    def update_candidate_person(
        self,
        conn,
        *,
        candidate_id: int,
        person_id: int,
        reason: str = "",
    ) -> dict:
        now = isoformat_z()
        conn.execute(
            """
            UPDATE fact_candidates
            SET person_id = ?,
                reason = CASE WHEN ? != '' THEN ? ELSE reason END,
                updated_at = ?
            WHERE id = ?
            """,
            (person_id, reason, reason, now, candidate_id),
        )
        return self.get_candidate(conn, candidate_id=candidate_id)

    def update_candidate_evidence(
        self,
        conn,
        *,
        candidate_id: int,
        evidence: list[dict],
    ) -> dict:
        now = isoformat_z()
        conn.execute(
            """
            UPDATE fact_candidates
            SET evidence_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(evidence, ensure_ascii=False), now, candidate_id),
        )
        return self.get_candidate(conn, candidate_id=candidate_id)

    def update_candidate_confidence(
        self,
        conn,
        *,
        candidate_id: int,
        confidence: float,
    ) -> dict:
        now = isoformat_z()
        conn.execute(
            """
            UPDATE fact_candidates
            SET confidence = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (confidence, now, candidate_id),
        )
        return self.get_candidate(conn, candidate_id=candidate_id)

    def update_candidate_payload(
        self,
        conn,
        *,
        candidate_id: int,
        payload: dict,
        reason: str = "",
    ) -> dict:
        now = isoformat_z()
        conn.execute(
            """
            UPDATE fact_candidates
            SET payload_json = ?,
                reason = CASE WHEN ? != '' THEN ? ELSE reason END,
                updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), reason, reason, now, candidate_id),
        )
        return self.get_candidate(conn, candidate_id=candidate_id)

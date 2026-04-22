from __future__ import annotations

import json
import re


SEARCH_TERM_RE = re.compile(r"[^\W_]+", re.UNICODE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


FIELD_BOOSTS = {
    "biography": {
        "residence": ("city", "place"),
        "origin": ("place",),
        "identity": ("name",),
        "education": ("institution", "field"),
        "family": ("relation", "name"),
        "pets": ("pet_type", "pet_name"),
        "languages": ("languages",),
        "habits": ("habit",),
        "goals": ("goal",),
        "constraints": ("constraint",),
    },
    "preferences": {
        "preference": ("value", "polarity", "reason"),
    },
    "social_circle": {
        "friend": ("target_label", "relation"),
        "manager": ("target_label", "relation"),
        "relationship_event": ("target_label", "event", "context"),
    },
    "work": {
        "employment": ("title",),
        "role": ("role",),
        "org": ("org",),
        "project": ("project",),
        "skill": ("skill",),
        "tool": ("tool",),
    },
    "experiences": {
        "event": ("event", "summary", "participants", "outcome", "event_at", "valence"),
    },
}


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
        sql += " ORDER BY observed_at DESC, id DESC"
        rows = conn.execute(sql, params).fetchall()
        terms = [term.lower() for term in SEARCH_TERM_RE.findall(query)]
        hits: list[dict] = []
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json") or "{}")
            evidence_rows = conn.execute(
                """
                SELECT id AS evidence_id, source_id, chunk_id, source_segment_id, session_id, quote_text, locator_json, support_type, source_confidence
                FROM memory_evidence
                WHERE fact_id = ?
                ORDER BY id ASC
                """,
                (int(item["id"]),),
            ).fetchall()
            evidence = [
                {
                    **dict(evidence_row),
                    "locator_json": json.loads(dict(evidence_row).get("locator_json") or "{}"),
                }
                for evidence_row in evidence_rows
            ]
            score = self._score_fact(
                query=query,
                terms=terms,
                fact=item,
                payload=payload,
                evidence=evidence,
                temporal_mode=temporal_mode,
            )
            if terms and score <= 0:
                continue
            hits.append(
                {
                    "fact_id": int(item["id"]),
                    "domain": item["domain"],
                    "category": item["category"],
                    "sensitivity": item.get("sensitivity", "normal"),
                    "visibility": item.get("visibility", "standard"),
                    "summary": item["summary"],
                    "confidence": float(item["confidence"]),
                    "score": score,
                    "status": item["status"],
                    "source_kind": item["source_kind"],
                    "observed_at": item["observed_at"],
                    "valid_from": item["valid_from"],
                    "valid_to": item["valid_to"],
                    "event_at": item.get("event_at", ""),
                    "payload": payload,
                    "evidence": evidence,
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
              cc.session_id,
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
                    "session_id": int(item["session_id"]) if item.get("session_id") is not None else None,
                    "text": item.get("text") or "",
                    "score": score,
                }
            )
        hits.sort(key=lambda hit: (-hit["score"], -hit["chunk_id"]))
        return hits[:limit]

    def _score_fact(
        self,
        *,
        query: str,
        terms: list[str],
        fact: dict,
        payload: dict,
        evidence: list[dict],
        temporal_mode: str,
    ) -> float:
        score = 0.0
        confidence = float(fact.get("confidence", 0.0))
        score += confidence

        domain = str(fact.get("domain") or "")
        category = str(fact.get("category") or "")
        summary = str(fact.get("summary") or "").lower()
        canonical_key = str(fact.get("canonical_key") or "").lower()
        payload_blob = json.dumps(payload, ensure_ascii=False).lower()

        field_names = FIELD_BOOSTS.get(domain, {}).get(category, ())
        field_values = []
        for field_name in field_names:
            value = payload.get(field_name)
            if isinstance(value, list):
                field_values.extend(str(item).lower() for item in value)
            elif value is not None:
                field_values.append(str(value).lower())

        for term in terms:
            if term in field_values:
                score += 2.5
            elif term in summary:
                score += 1.25
            elif term in payload_blob:
                score += 1.0
            elif term in canonical_key:
                score += 0.8

        evidence_quality = self._evidence_quality(evidence)
        score += evidence_quality
        if temporal_mode == "current":
            score += self._current_mode_weight(payload)
        if temporal_mode == "history" and fact.get("status") == "superseded":
            score += 1.0
        if fact.get("status") == "superseded" and temporal_mode != "history":
            score -= 0.5
        score += self._freshness_adjustment(str(fact.get("observed_at") or ""))
        score -= self._sensitivity_penalty(payload)
        return score

    def _evidence_quality(self, evidence: list[dict]) -> float:
        if not evidence:
            return 0.0
        best_confidence = max(float(item.get("source_confidence") or 0.0) for item in evidence)
        coverage_bonus = min(len(evidence), 3) * 0.2
        return best_confidence * 0.8 + coverage_bonus

    def _current_mode_weight(self, payload: dict) -> float:
        if "is_current" in payload:
            return 1.2 if payload.get("is_current") is True else -1.2
        return 0.0

    def _freshness_adjustment(self, observed_at: str) -> float:
        if not observed_at:
            return 0.0
        year_match = YEAR_RE.search(observed_at)
        if not year_match:
            return 0.0
        year = int(year_match.group(0))
        delta = year - 2026
        if delta >= 0:
            return min(delta * 0.05, 0.15)
        return max(delta * 0.1, -0.5)

    def _sensitivity_penalty(self, payload: dict) -> float:
        if payload.get("sensitivity") == "high":
            return 0.5
        return 0.0

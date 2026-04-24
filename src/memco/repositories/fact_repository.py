from __future__ import annotations

import json

from memco.consolidation import get_policy
from memco.repositories.source_repository import SourceRepository
from memco.utils import isoformat_z, json_dumps, slugify


class FactRepository:
    SENSITIVE_FACT_CATEGORIES = {
        ("biography", "family"),
        ("biography", "constraints"),
        ("biography", "identity"),
        ("biography", "origin"),
        ("psychometrics", "trait"),
    }

    def ensure_workspace(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is not None:
            return int(row["id"])
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO workspaces (slug, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (slug, slug.replace("-", " ").title(), now, now),
        )
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise RuntimeError("Failed to ensure workspace")
        return int(row["id"])

    def upsert_person(self, conn, *, workspace_slug: str, display_name: str, slug: str | None, person_type: str, aliases: list[str]) -> dict:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        now = isoformat_z()
        person_slug = slugify(slug or display_name)
        conn.execute(
            """
            INSERT INTO persons (workspace_id, slug, display_name, person_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(workspace_id, slug) DO UPDATE SET
                display_name = excluded.display_name,
                person_type = excluded.person_type,
                updated_at = excluded.updated_at
            """,
            (workspace_id, person_slug, display_name, person_type, now, now),
        )
        row = conn.execute(
            "SELECT * FROM persons WHERE workspace_id = ? AND slug = ?",
            (workspace_id, person_slug),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert person")
        person = dict(row)
        for alias in aliases:
            self.upsert_person_alias(
                conn,
                workspace_slug=workspace_slug,
                person_id=int(person["id"]),
                alias=alias,
                alias_type="name",
            )
        return person

    def upsert_person_alias(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        alias: str,
        alias_type: str = "name",
    ) -> dict:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        normalized = " ".join(alias.strip().lower().split())
        if not normalized:
            raise ValueError("Alias cannot be empty")
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO person_aliases (
                workspace_id, person_id, alias, alias_type, normalized_alias, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, 1.0, ?)
            ON CONFLICT(workspace_id, normalized_alias, alias_type) DO UPDATE SET
                person_id = excluded.person_id,
                alias = excluded.alias,
                confidence = excluded.confidence
            """,
            (workspace_id, person_id, alias, alias_type, normalized, now),
        )
        row = conn.execute(
            """
            SELECT alias, alias_type, normalized_alias, confidence
            FROM person_aliases
            WHERE workspace_id = ? AND person_id = ? AND normalized_alias = ? AND alias_type = ?
            """,
            (workspace_id, person_id, normalized, alias_type),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert alias")
        return dict(row)

    def resolve_person_id(self, conn, *, workspace_slug: str, person_id: int | None = None, person_slug: str | None = None) -> int:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        if person_id is not None:
            row = conn.execute(
                "SELECT id FROM persons WHERE workspace_id = ? AND id = ?",
                (workspace_id, person_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM persons WHERE workspace_id = ? AND slug = ?",
                (workspace_id, slugify(person_slug or "")),
            ).fetchone()
        if row is None:
            raise ValueError("Unknown person")
        return int(row["id"])

    def add_fact(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        domain: str,
        category: str,
        subcategory: str,
        canonical_key: str,
        payload: dict,
        summary: str,
        source_kind: str,
        confidence: float,
        observed_at: str,
        valid_from: str,
        valid_to: str,
        event_at: str,
        source_id: int,
        quote_text: str,
        source_chunk_id: int | None = None,
        source_segment_id: int | None = None,
        session_id: int | None = None,
        support_type: str = "supports",
        supersedes_fact_id: int | None = None,
        locator: dict | None = None,
    ) -> dict:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        now = isoformat_z()
        policy = get_policy(domain)
        sensitivity, visibility = self.classify_fact_access(domain=domain, category=category)
        normalized_chunk_id = source_chunk_id
        if normalized_chunk_id is not None:
            row = conn.execute("SELECT id FROM source_chunks WHERE id = ?", (normalized_chunk_id,)).fetchone()
            if row is None:
                normalized_chunk_id = None
        duplicate = self.find_duplicate_fact(
            conn,
            workspace_slug=workspace_slug,
            person_id=person_id,
            domain=domain,
            category=category,
            canonical_key=canonical_key,
            payload=payload,
            semantic_payload=self._semantic_payload(
                payload=payload,
                observed_at=observed_at,
                valid_from=valid_from,
                valid_to=valid_to,
                event_at=event_at,
            ),
        )
        if duplicate is not None:
            self.add_evidence(
                conn,
                fact_id=int(duplicate["id"]),
                source_id=source_id,
                source_chunk_id=normalized_chunk_id,
                source_segment_id=source_segment_id,
                session_id=session_id,
                quote_text=quote_text,
                support_type=support_type,
                source_confidence=confidence,
                locator=locator,
            )
            conn.execute(
                """
                INSERT INTO memory_operations (
                    workspace_id, person_id, operation_type, target_fact_id, before_json, after_json, reason, created_at
                ) VALUES (?, ?, 'merge', ?, '{}', ?, ?, ?)
                """,
                (
                    workspace_id,
                    person_id,
                    int(duplicate["id"]),
                    json_dumps({"source_id": source_id, "canonical_key": canonical_key}),
                    "duplicate fact merged by canonical key",
                    now,
                ),
            )
            return self.get_fact(conn, fact_id=int(duplicate["id"]))
        decision = policy.resolve(
            category=category,
            canonical_key=canonical_key,
            payload=payload,
            observed_at=observed_at,
            existing_fact=None,
        )
        previous = None
        if supersedes_fact_id is None:
            previous = self.find_current_fact(
                conn,
                workspace_slug=workspace_slug,
                person_id=person_id,
                domain=domain,
                category=category,
                canonical_key=canonical_key,
            )
            if previous is not None:
                decision = policy.resolve(
                    category=category,
                    canonical_key=canonical_key,
                    payload=payload,
                    observed_at=observed_at,
                    existing_fact=previous,
                )
                if decision.action == "supersede_existing":
                    supersedes_fact_id = int(previous["id"])
        inserted_status = "active"
        superseded_by_fact_id = None
        if decision.action == "insert_historical" and previous is not None:
            inserted_status = "superseded"
            superseded_by_fact_id = int(previous["id"])
        cursor = conn.execute(
            """
            INSERT INTO memory_facts (
                workspace_id, person_id, domain, category, subcategory, canonical_key,
                payload_json, summary, status, sensitivity, visibility, confidence, source_kind, observed_at,
                valid_from, valid_to, event_at, supersedes_fact_id, superseded_by_fact_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                person_id,
                domain,
                category,
                subcategory,
                canonical_key,
                json_dumps(payload),
                summary,
                inserted_status,
                sensitivity,
                visibility,
                confidence,
                source_kind,
                observed_at,
                valid_from,
                valid_to,
                event_at,
                supersedes_fact_id,
                superseded_by_fact_id,
                now,
                now,
            ),
        )
        fact_id = int(cursor.lastrowid)
        if supersedes_fact_id is not None:
            conn.execute(
                """
                UPDATE memory_facts
                SET valid_to = CASE WHEN valid_to = '' THEN ? ELSE valid_to END,
                    updated_at = ?
                WHERE id = ?
                """,
                (observed_at, now, supersedes_fact_id),
            )
            self.mark_fact_status(
                conn,
                fact_id=supersedes_fact_id,
                status="superseded",
                reason=f"Superseded by fact {fact_id}",
                superseded_by_fact_id=fact_id,
            )
        if self.is_current_state_category(domain=domain, category=category):
            conn.execute(
                """
                UPDATE memory_facts
                SET valid_from = CASE WHEN valid_from = '' THEN ? ELSE valid_from END
                WHERE id = ?
                """,
                (observed_at, fact_id),
            )
        self.add_evidence(
            conn,
            fact_id=fact_id,
            source_id=source_id,
            source_chunk_id=normalized_chunk_id,
            source_segment_id=source_segment_id,
            session_id=session_id,
            quote_text=quote_text,
            support_type=support_type,
            source_confidence=confidence,
            locator=locator,
        )
        conn.execute(
            """
            INSERT INTO memory_operations (
                workspace_id, person_id, operation_type, target_fact_id, before_json, after_json, reason, created_at
                ) VALUES (?, ?, 'add', ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                person_id,
                fact_id,
                json_dumps({"supersedes_fact_id": supersedes_fact_id, "conflict_kind": decision.conflict_kind} if supersedes_fact_id else {"conflict_kind": decision.conflict_kind}),
                json_dumps({"canonical_key": canonical_key, "domain": domain, "category": category, "status": inserted_status}),
                decision.reason,
                now,
            ),
        )
        return self.get_fact(conn, fact_id=fact_id)

    def classify_fact_access(self, *, domain: str, category: str) -> tuple[str, str]:
        if (domain, category) in self.SENSITIVE_FACT_CATEGORIES:
            return "high", "owner_only"
        return "normal", "standard"

    def find_duplicate_fact(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        domain: str,
        category: str,
        canonical_key: str,
        payload: dict,
        semantic_payload: dict | None = None,
    ) -> dict | None:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        row = conn.execute(
            """
            SELECT *
            FROM memory_facts
            WHERE workspace_id = ? AND person_id = ? AND domain = ? AND category = ?
              AND canonical_key = ? AND payload_json = ? AND status = 'active'
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (workspace_id, person_id, domain, category, canonical_key, json_dumps(payload)),
        ).fetchone()
        if row is not None:
            return dict(row)
        policy = get_policy(domain)
        semantic_key = policy.semantic_duplicate_key(category=category, payload=semantic_payload or payload)
        if not semantic_key:
            return None
        rows = conn.execute(
            """
            SELECT *
            FROM memory_facts
            WHERE workspace_id = ? AND person_id = ? AND domain = ? AND category = ? AND status = 'active'
            ORDER BY observed_at DESC, id DESC
            """,
            (workspace_id, person_id, domain, category),
        ).fetchall()
        for candidate in rows:
            candidate_payload = self._semantic_payload(
                payload=json.loads(candidate["payload_json"] or "{}"),
                observed_at=str(candidate["observed_at"] or ""),
                valid_from=str(candidate["valid_from"] or ""),
                valid_to=str(candidate["valid_to"] or ""),
                event_at=str(candidate["event_at"] or ""),
            )
            if policy.semantic_duplicate_key(category=category, payload=candidate_payload) == semantic_key:
                return dict(candidate)
        return None

    def _semantic_payload(
        self,
        *,
        payload: dict,
        observed_at: str = "",
        valid_from: str = "",
        valid_to: str = "",
        event_at: str = "",
    ) -> dict:
        semantic_payload = dict(payload)
        for key, value in {
            "observed_at": observed_at,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "event_at": event_at,
        }.items():
            if value:
                semantic_payload.setdefault(key, value)
        return semantic_payload

    def add_evidence(
        self,
        conn,
        *,
        fact_id: int,
        source_id: int,
        source_chunk_id: int | None,
        source_segment_id: int | None,
        session_id: int | None,
        quote_text: str,
        support_type: str,
        source_confidence: float,
        locator: dict | None = None,
    ) -> None:
        locator_json = json_dumps(locator or {})
        normalized_segment_id = source_segment_id
        if normalized_segment_id is None and source_chunk_id is not None:
            segment = SourceRepository().get_segment_by_chunk_id(conn, chunk_id=source_chunk_id)
            if segment is not None:
                normalized_segment_id = int(segment["id"])
        existing = conn.execute(
            """
            SELECT id
            FROM memory_evidence
            WHERE fact_id = ? AND source_id = ? AND COALESCE(chunk_id, -1) = COALESCE(?, -1)
              AND COALESCE(source_segment_id, -1) = COALESCE(?, -1)
              AND COALESCE(session_id, -1) = COALESCE(?, -1)
              AND quote_text = ? AND locator_json = ?
            LIMIT 1
            """,
            (fact_id, source_id, source_chunk_id, normalized_segment_id, session_id, quote_text, locator_json),
        ).fetchone()
        if existing is not None:
            return
        conn.execute(
            """
            INSERT INTO memory_evidence (
                fact_id, source_id, chunk_id, source_segment_id, session_id, quote_text, locator_json, support_type, source_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                source_id,
                source_chunk_id,
                normalized_segment_id,
                session_id,
                quote_text,
                locator_json,
                support_type,
                source_confidence,
            ),
        )

    def get_operation(self, conn, *, operation_id: int) -> dict:
        row = conn.execute("SELECT * FROM memory_operations WHERE id = ?", (operation_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown operation")
        item = dict(row)
        item["before"] = json.loads(item.pop("before_json") or "{}")
        item["after"] = json.loads(item.pop("after_json") or "{}")
        return item

    def rollback_operation(self, conn, *, operation_id: int, reason: str = "") -> dict:
        operation = self.get_operation(conn, operation_id=operation_id)
        operation_type = operation["operation_type"]
        target_fact_id = operation.get("target_fact_id")
        if target_fact_id is None:
            raise ValueError("Operation has no target fact")
        rollback_before = {"operation_id": operation_id, "operation_type": operation_type}
        rollback_after: dict[str, object]
        if operation_type == "add":
            self.mark_fact_status(conn, fact_id=int(target_fact_id), status="deleted", reason=reason or "rollback:add")
            rollback_after = {"status": self.get_fact(conn, fact_id=int(target_fact_id))["status"]}
        elif operation_type == "deleted":
            self.mark_fact_status(conn, fact_id=int(target_fact_id), status="active", reason=reason or "rollback:delete")
            rollback_after = {"status": self.get_fact(conn, fact_id=int(target_fact_id))["status"]}
        elif operation_type == "superseded":
            target_before = self.get_fact(conn, fact_id=int(target_fact_id))
            successor_fact_id = operation["after"].get("superseded_by_fact_id") or target_before.get("superseded_by_fact_id")
            successor_before = None
            if successor_fact_id is not None:
                try:
                    successor_before = self.get_fact(conn, fact_id=int(successor_fact_id))
                except ValueError:
                    successor_before = None
            now = isoformat_z()
            conn.execute(
                """
                UPDATE memory_facts
                SET status = 'active',
                    superseded_by_fact_id = NULL,
                    valid_to = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, target_fact_id),
            )
            target_row = conn.execute("SELECT workspace_id, person_id FROM memory_facts WHERE id = ?", (target_fact_id,)).fetchone()
            if target_row is not None:
                conn.execute(
                    """
                    INSERT INTO memory_operations (
                        workspace_id, person_id, operation_type, target_fact_id, before_json, after_json, reason, created_at
                    ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?)
                    """,
                    (
                        int(target_row["workspace_id"]),
                        int(target_row["person_id"]),
                        int(target_fact_id),
                        json_dumps(
                            {
                                "status": target_before["status"],
                                "superseded_by_fact_id": target_before.get("superseded_by_fact_id"),
                                "valid_to": target_before.get("valid_to"),
                            }
                        ),
                        json_dumps(
                            {
                                "status": "active",
                                "superseded_by_fact_id": None,
                                "valid_to": "",
                            }
                        ),
                        reason or "rollback:supersede",
                        now,
                    ),
                )
            if successor_before is not None:
                conn.execute(
                    """
                    UPDATE memory_facts
                    SET status = 'deleted',
                        supersedes_fact_id = CASE
                            WHEN supersedes_fact_id = ? THEN NULL
                            ELSE supersedes_fact_id
                        END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (int(target_fact_id), now, int(successor_fact_id)),
                )
                successor_row = conn.execute(
                    "SELECT workspace_id, person_id FROM memory_facts WHERE id = ?",
                    (int(successor_fact_id),),
                ).fetchone()
                if successor_row is not None:
                    conn.execute(
                        """
                        INSERT INTO memory_operations (
                            workspace_id, person_id, operation_type, target_fact_id, before_json, after_json, reason, created_at
                        ) VALUES (?, ?, 'deleted', ?, ?, ?, ?, ?)
                        """,
                        (
                            int(successor_row["workspace_id"]),
                            int(successor_row["person_id"]),
                            int(successor_fact_id),
                            json_dumps(
                                {
                                    "status": successor_before["status"],
                                    "supersedes_fact_id": successor_before.get("supersedes_fact_id"),
                                }
                            ),
                            json_dumps(
                                {
                                    "status": "deleted",
                                    "supersedes_fact_id": None,
                                    "rollback_of_operation_id": operation_id,
                                    "rolled_back_target_fact_id": int(target_fact_id),
                                }
                            ),
                            reason or f"rollback:supersede demoted successor {successor_fact_id}",
                            now,
                        ),
                    )
            active_rows = conn.execute(
                """
                SELECT id
                FROM memory_facts
                WHERE workspace_id = ? AND person_id = ? AND domain = ? AND category = ? AND status = 'active'
                ORDER BY observed_at DESC, id DESC
                """,
                (
                    int(target_before["workspace_id"]),
                    int(target_before["person_id"]),
                    target_before["domain"],
                    target_before["category"],
                ),
            ).fetchall()
            rollback_before.update(
                {
                    "target_fact_status_before": target_before["status"],
                    "target_superseded_by_fact_id_before": target_before.get("superseded_by_fact_id"),
                    "successor_fact_id": successor_fact_id,
                    "successor_status_before": successor_before["status"] if successor_before else None,
                    "successor_supersedes_fact_id_before": successor_before.get("supersedes_fact_id") if successor_before else None,
                }
            )
            rollback_after = {
                "canceled_supersede": {
                    "target_fact_id": int(target_fact_id),
                    "successor_fact_id": int(successor_fact_id) if successor_fact_id is not None else None,
                },
                "reactivated_fact_id": int(target_fact_id),
                "demoted_successor_fact_id": int(successor_fact_id) if successor_before is not None else None,
                "truth_store": {
                    "active_fact_ids": [int(row["id"]) for row in active_rows],
                },
            }
        else:
            raise ValueError(f"Rollback unsupported for operation type: {operation_type}")
        row = conn.execute("SELECT workspace_id, person_id FROM memory_facts WHERE id = ?", (target_fact_id,)).fetchone()
        now = isoformat_z()
        if row is not None:
            conn.execute(
                """
                INSERT INTO memory_operations (
                    workspace_id, person_id, operation_type, target_fact_id, before_json, after_json, reason, created_at
                ) VALUES (?, ?, 'rollback', ?, ?, ?, ?, ?)
                """,
                (
                    int(row["workspace_id"]),
                    int(row["person_id"]),
                    int(target_fact_id),
                    json_dumps(rollback_before),
                    json_dumps(rollback_after),
                    reason or f"rollback of operation {operation_id}",
                    now,
                ),
            )
        return self.get_fact(conn, fact_id=int(target_fact_id))

    def is_current_state_category(self, *, domain: str, category: str) -> bool:
        return get_policy(domain).is_current_state(category)

    def find_current_fact(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        domain: str,
        category: str,
        canonical_key: str,
    ) -> dict | None:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        if self.is_current_state_category(domain=domain, category=category):
            row = conn.execute(
                """
                SELECT *
                FROM memory_facts
                WHERE workspace_id = ? AND person_id = ? AND domain = ? AND category = ? AND status = 'active'
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """,
                (workspace_id, person_id, domain, category),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT *
                FROM memory_facts
                WHERE workspace_id = ? AND person_id = ? AND canonical_key = ? AND status = 'active'
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """,
                (workspace_id, person_id, canonical_key),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_fact_status(
        self,
        conn,
        *,
        fact_id: int,
        status: str,
        reason: str = "",
        superseded_by_fact_id: int | None = None,
    ) -> dict:
        now = isoformat_z()
        conn.execute(
            """
            UPDATE memory_facts
            SET status = ?,
                superseded_by_fact_id = COALESCE(?, superseded_by_fact_id),
                updated_at = ?
            WHERE id = ?
            """,
            (status, superseded_by_fact_id, now, fact_id),
        )
        row = conn.execute("SELECT workspace_id, person_id FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        if row is not None:
            conn.execute(
                """
                INSERT INTO memory_operations (
                    workspace_id, person_id, operation_type, target_fact_id, before_json, after_json, reason, created_at
                ) VALUES (?, ?, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    int(row["workspace_id"]),
                    int(row["person_id"]),
                    status,
                    fact_id,
                    json_dumps({"status": status, "superseded_by_fact_id": superseded_by_fact_id}),
                    reason,
                    now,
                ),
            )
        return self.get_fact(conn, fact_id=fact_id)

    def list_facts(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        status: str | None = None,
        domain: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = "SELECT id FROM memory_facts WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if person_id is not None:
            sql += " AND person_id = ?"
            params.append(person_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        sql += " ORDER BY observed_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [self.get_fact(conn, fact_id=int(row["id"])) for row in rows]

    def list_operations(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        target_fact_id: int | None = None,
        operation_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = "SELECT * FROM memory_operations WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if person_id is not None:
            sql += " AND person_id = ?"
            params.append(person_id)
        if target_fact_id is not None:
            sql += " AND target_fact_id = ?"
            params.append(target_fact_id)
        if operation_type:
            sql += " AND operation_type = ?"
            params.append(operation_type)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [self.get_operation(conn, operation_id=int(row["id"])) for row in rows]

    def get_person(self, conn, *, workspace_slug: str, person_id: int | None = None, person_slug: str | None = None) -> dict | None:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        if person_id is not None:
            row = conn.execute(
                "SELECT * FROM persons WHERE workspace_id = ? AND id = ?",
                (workspace_id, person_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM persons WHERE workspace_id = ? AND slug = ?",
                (workspace_id, slugify(person_slug or "")),
            ).fetchone()
        if row is None:
            return None
        person = dict(row)
        aliases = conn.execute(
            """
            SELECT alias, alias_type, normalized_alias, confidence
            FROM person_aliases
            WHERE workspace_id = ? AND person_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (workspace_id, int(person["id"])),
        ).fetchall()
        person["aliases"] = [dict(alias) for alias in aliases]
        return person

    def list_persons(self, conn, *, workspace_slug: str, status: str | None = None, limit: int = 100) -> list[dict]:
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        sql = "SELECT * FROM persons WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [self.get_person(conn, workspace_slug=workspace_slug, person_id=int(row["id"])) for row in rows]

    def merge_persons(
        self,
        conn,
        *,
        workspace_slug: str,
        from_person_id: int,
        to_person_id: int,
        reason: str = "",
    ) -> dict:
        if from_person_id == to_person_id:
            raise ValueError("Cannot merge a person into itself")
        workspace_id = self.ensure_workspace(conn, workspace_slug)
        now = isoformat_z()
        conn.execute(
            """
            INSERT INTO person_merges (workspace_id, from_person_id, to_person_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (workspace_id, from_person_id, to_person_id, reason, now),
        )
        conn.execute(
            "UPDATE person_aliases SET person_id = ? WHERE workspace_id = ? AND person_id = ?",
            (to_person_id, workspace_id, from_person_id),
        )
        conn.execute(
            "UPDATE conversation_messages SET speaker_person_id = ? WHERE speaker_person_id = ?",
            (to_person_id, from_person_id),
        )
        conn.execute(
            "UPDATE conversation_speaker_map SET person_id = ?, resolution_method = 'merged' WHERE person_id = ?",
            (to_person_id, from_person_id),
        )
        conn.execute(
            "UPDATE fact_candidates SET person_id = ? WHERE workspace_id = ? AND person_id = ?",
            (to_person_id, workspace_id, from_person_id),
        )
        conn.execute(
            "UPDATE review_queue SET person_id = ? WHERE workspace_id = ? AND person_id = ?",
            (to_person_id, workspace_id, from_person_id),
        )
        conn.execute(
            "UPDATE memory_facts SET person_id = ? WHERE workspace_id = ? AND person_id = ?",
            (to_person_id, workspace_id, from_person_id),
        )
        conn.execute(
            "UPDATE memory_operations SET person_id = ? WHERE workspace_id = ? AND person_id = ?",
            (to_person_id, workspace_id, from_person_id),
        )
        conn.execute(
            "UPDATE retrieval_logs SET person_id = ? WHERE workspace_id = ? AND person_id = ?",
            (to_person_id, workspace_id, from_person_id),
        )
        conn.execute(
            "UPDATE persons SET status = 'merged', updated_at = ? WHERE workspace_id = ? AND id = ?",
            (now, workspace_id, from_person_id),
        )
        return {
            "from_person_id": from_person_id,
            "to_person_id": to_person_id,
            "reason": reason,
            "merged_at": now,
        }

    def get_fact(self, conn, *, fact_id: int) -> dict:
        row = conn.execute("SELECT * FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown fact")
        fact = dict(row)
        fact["payload"] = json.loads(fact.pop("payload_json") or "{}")
        evidence_rows = conn.execute(
            """
            SELECT id AS evidence_id, source_id, chunk_id, source_segment_id, session_id, quote_text, locator_json, support_type, source_confidence
            FROM memory_evidence
            WHERE fact_id = ?
            ORDER BY id ASC
            """,
            (fact_id,),
        ).fetchall()
        fact["evidence"] = [
            {
                **dict(evidence),
                "locator_json": json.loads(dict(evidence)["locator_json"] or "{}"),
            }
            for evidence in evidence_rows
        ]
        return fact

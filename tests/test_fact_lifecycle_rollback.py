from __future__ import annotations

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService
from memco.services.retrieval_service import RetrievalService
from memco.models.retrieval import RetrievalRequest


def test_rollback_reverts_deleted_fact(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/rollback.md",
            source_type="note",
            origin_uri="/tmp/rollback.md",
            title="rollback",
            sha256="rollback-sha",
            parsed_text="Alice lives in Lisbon.",
        )
        fact = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Alice lives in Lisbon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
            locator={"message_ids": ["1"]},
        )
        deleted = consolidation.mark_deleted(conn, fact_id=int(fact["id"]), reason="cleanup")
        delete_operation = conn.execute(
            "SELECT id FROM memory_operations WHERE target_fact_id = ? AND operation_type = 'deleted' ORDER BY id DESC LIMIT 1",
            (int(fact["id"]),),
        ).fetchone()
        rolled_back = consolidation.rollback(conn, operation_id=int(delete_operation["id"]), reason="undo cleanup")
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )

    assert deleted["status"] == "deleted"
    assert rolled_back["status"] == "active"
    assert result.hits[0].payload["city"] == "Lisbon"


def test_rollback_reverts_superseded_current_state_fact(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/rollback-supersede.md",
            source_type="note",
            origin_uri="/tmp/rollback-supersede.md",
            title="rollback-supersede",
            sha256="rollback-supersede-sha",
            parsed_text="Alice lived in Berlin and later moved to Lisbon.",
        )
        old_fact = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Alice lives in Berlin.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lived in Berlin.",
            ),
            locator={"message_ids": ["1"]},
        )
        new_fact = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Alice lives in Lisbon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice moved to Lisbon.",
            ),
            locator={"message_ids": ["2"]},
        )
        supersede_operation = conn.execute(
            "SELECT id FROM memory_operations WHERE target_fact_id = ? AND operation_type = 'superseded' ORDER BY id DESC LIMIT 1",
            (int(old_fact["id"]),),
        ).fetchone()

        rolled_back = consolidation.rollback(conn, operation_id=int(supersede_operation["id"]), reason="undo supersede")
        refreshed_old = fact_repo.get_fact(conn, fact_id=int(old_fact["id"]))
        refreshed_new = fact_repo.get_fact(conn, fact_id=int(new_fact["id"]))
        current = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )
        history = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Where did Alice live before Lisbon?",
                temporal_mode="history",
            ),
        )
        active_facts = conn.execute(
            """
            SELECT id
            FROM memory_facts
            WHERE workspace_id = ? AND person_id = ? AND domain = ? AND category = ? AND status = 'active'
            ORDER BY observed_at DESC, id DESC
            """,
            (
                int(refreshed_old["workspace_id"]),
                int(refreshed_old["person_id"]),
                refreshed_old["domain"],
                refreshed_old["category"],
            ),
        ).fetchall()
        rollback_operation = conn.execute(
            "SELECT id FROM memory_operations WHERE operation_type = 'rollback' AND target_fact_id = ? ORDER BY id DESC LIMIT 1",
            (int(old_fact["id"]),),
        ).fetchone()
        rollback_record = fact_repo.get_operation(conn, operation_id=int(rollback_operation["id"]))
        restored_operation = conn.execute(
            "SELECT id FROM memory_operations WHERE operation_type = 'active' AND target_fact_id = ? ORDER BY id DESC LIMIT 1",
            (int(old_fact["id"]),),
        ).fetchone()
        restored_record = fact_repo.get_operation(conn, operation_id=int(restored_operation["id"]))
        demoted_operation = conn.execute(
            "SELECT id FROM memory_operations WHERE operation_type = 'deleted' AND target_fact_id = ? ORDER BY id DESC LIMIT 1",
            (int(new_fact["id"]),),
        ).fetchone()
        demoted_record = fact_repo.get_operation(conn, operation_id=int(demoted_operation["id"]))

    assert rolled_back["status"] == "active"
    assert refreshed_old["status"] == "active"
    assert refreshed_old["superseded_by_fact_id"] is None
    assert refreshed_old["valid_to"] == ""
    assert refreshed_new["status"] != "active"
    assert refreshed_new["status"] == "deleted"
    assert refreshed_new["supersedes_fact_id"] is None
    assert [int(row["id"]) for row in active_facts] == [int(old_fact["id"])]
    assert [hit.fact_id for hit in current.hits] == [int(old_fact["id"])]
    assert current.hits[0].payload["city"] == "Berlin"
    assert [hit.fact_id for hit in history.hits] == [int(old_fact["id"])]
    assert history.hits[0].payload["city"] == "Berlin"
    assert all(hit.status == "active" for hit in history.hits)
    assert all(hit.fact_id != int(new_fact["id"]) for hit in history.hits)
    assert restored_record["before"]["status"] == "superseded"
    assert restored_record["after"]["status"] == "active"
    assert restored_record["after"]["superseded_by_fact_id"] is None
    assert demoted_record["before"]["status"] == "active"
    assert demoted_record["before"]["supersedes_fact_id"] == int(old_fact["id"])
    assert demoted_record["after"]["status"] == "deleted"
    assert demoted_record["after"]["supersedes_fact_id"] is None
    assert rollback_record["before"]["operation_type"] == "superseded"
    assert rollback_record["before"]["successor_fact_id"] == int(new_fact["id"])
    assert rollback_record["after"]["demoted_successor_fact_id"] == int(new_fact["id"])
    assert rollback_record["after"]["truth_store"]["active_fact_ids"] == [int(old_fact["id"])]

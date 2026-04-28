from __future__ import annotations

from memco.config import load_settings
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.models.retrieval import RetrievalRequest
from memco.repositories.fact_repository import FactRepository
from memco.repositories.retrieval_log_repository import RetrievalLogRepository
from memco.repositories.source_repository import SourceRepository
from memco.api.deps import build_internal_actor
from memco.services.consolidation_service import ConsolidationService
from memco.services.retrieval_service import RetrievalService


def test_retrieval_logs_are_redacted(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()
    log_repo = RetrievalLogRepository()
    loaded_settings = load_settings(settings.root)
    actor = build_internal_actor(loaded_settings, actor_id="dev-owner")

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
            source_path="var/raw/logging.md",
            source_type="note",
            origin_uri="/tmp/logging.md",
            title="logging",
            sha256="logging-sha",
            parsed_text="Alice lives in Lisbon.",
        )
        consolidation.add_fact(
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
        )
        retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?", actor=actor),
            settings=loaded_settings,
            route_name="retrieve",
        )
        logs = log_repo.list_logs(conn, workspace_slug="default")

    assert len(logs) == 1
    log = logs[0]
    assert log["query_hash"] != "Where does Alice live?"
    assert log["query_length"] == len("Where does Alice live?")
    assert log["fact_hit_count"] == 1
    assert log["fact_ids"] != []
    assert "Lisbon" not in str(log)
    assert "Alice lives in Lisbon." not in str(log)


def test_retrieval_logs_store_fallback_refs_without_chunk_text(settings, tmp_path):
    from memco.services.conversation_ingest_service import ConversationIngestService
    from memco.services.ingest_service import IngestService

    retrieval = RetrievalService()
    log_repo = RetrievalLogRepository()
    loaded_settings = load_settings(settings.root)
    actor = build_internal_actor(loaded_settings, actor_id="dev-owner")
    source = tmp_path / "fallback-log.json"
    source.write_text(
        '{"messages":[{"speaker":"Alice","timestamp":"2026-04-21T10:00:00Z","text":"I attended PyCon."}]}',
        encoding="utf-8",
    )

    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        imported = IngestService().import_file(
            loaded_settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        ConversationIngestService().import_conversation(
            loaded_settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="What memories mention attended?", actor=actor),
            settings=loaded_settings,
            route_name="retrieve",
        )
        logs = log_repo.list_logs(conn, workspace_slug="default")

    assert len(logs) == 1
    log = logs[0]
    assert log["fallback_hit_count"] >= 1
    assert log["fallback_refs"][0]["chunk_id"] > 0
    assert "PyCon" not in str(log["fallback_refs"])


def test_retrieval_logs_include_temporal_mode_in_domain_filter(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()
    log_repo = RetrievalLogRepository()
    loaded_settings = load_settings(settings.root)
    actor = build_internal_actor(loaded_settings, actor_id="dev-owner")

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
            source_path="var/raw/logging-history.md",
            source_type="note",
            origin_uri="/tmp/logging-history.md",
            title="logging-history",
            sha256="logging-history-sha",
            parsed_text="Alice lived in Berlin. Alice moved to Lisbon.",
        )
        consolidation.add_fact(
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
        )
        consolidation.add_fact(
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
        )
        retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where did Alice live before Lisbon?", temporal_mode="history", actor=actor),
            settings=loaded_settings,
            route_name="retrieve",
        )
        logs = log_repo.list_logs(conn, workspace_slug="default")

    assert logs[0]["domain_filter"].endswith("history")


def test_retrieval_logs_include_redacted_category_rag_constraints(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()
    log_repo = RetrievalLogRepository()
    loaded_settings = load_settings(settings.root)
    actor = build_internal_actor(loaded_settings, actor_id="dev-owner")

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
            source_path="var/raw/logging-current-residence.md",
            source_type="note",
            origin_uri="/tmp/logging-current-residence.md",
            title="logging-current-residence",
            sha256="logging-current-residence-sha",
            parsed_text="Alice moved to Lisbon.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:lisbon-current",
                payload={"city": "Lisbon", "is_current": True},
                summary="Alice lives in Lisbon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice moved to Lisbon.",
            ),
        )
        retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live now?", actor=actor),
            settings=loaded_settings,
            route_name="retrieve",
        )
        logs = log_repo.list_logs(conn, workspace_slug="default")

    assert logs[0]["field_constraints"] == [
        {
            "domain": "biography",
            "category": "residence",
            "field_constraints": {"is_current": True, "valid_at": "now"},
        }
    ]
    assert "Lisbon" not in str(logs[0]["field_constraints"])


def test_retrieval_logs_can_be_filtered_by_person(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()
    log_repo = RetrievalLogRepository()
    loaded_settings = load_settings(settings.root)
    actor = build_internal_actor(loaded_settings, actor_id="dev-owner")

    with get_connection(settings.db_path) as conn:
        alice = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        bob = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/logging-filter.md",
            source_type="note",
            origin_uri="/tmp/logging-filter.md",
            title="logging-filter",
            sha256="logging-filter-sha",
            parsed_text="Alice lives in Lisbon. Bob lives in Porto.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(alice["id"]),
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
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(bob["id"]),
                domain="biography",
                category="residence",
                canonical_key="bob:biography:residence:porto",
                payload={"city": "Porto"},
                summary="Bob lives in Porto.",
                confidence=0.95,
                observed_at="2026-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Bob lives in Porto.",
            ),
        )
        retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?", actor=actor),
            settings=loaded_settings,
            route_name="retrieve",
        )
        retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="bob", query="Where does Bob live?", actor=actor),
            settings=loaded_settings,
            route_name="retrieve",
        )
        alice_logs = log_repo.list_logs(conn, workspace_slug="default", person_id=int(alice["id"]))
        bob_logs = log_repo.list_logs(conn, workspace_slug="default", person_id=int(bob["id"]))

    assert len(alice_logs) == 1
    assert len(bob_logs) == 1
    assert alice_logs[0]["person_id"] == int(alice["id"])
    assert bob_logs[0]["person_id"] == int(bob["id"])

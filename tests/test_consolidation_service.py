from __future__ import annotations

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService
from memco.services.retrieval_service import RetrievalService
from memco.models.retrieval import RetrievalRequest


def test_add_fact_persists_fact_and_evidence(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/note.md",
            source_type="note",
            origin_uri="/tmp/note.md",
            title="note",
            sha256="abc123",
            parsed_text="Alice likes tea.",
        )
        payload = MemoryFactInput(
            workspace="default",
            person_id=int(person["id"]),
            domain="preferences",
            category="food_drink",
            canonical_key="alice:preferences:drink.favorite:tea",
            payload={"value": "tea"},
            summary="Alice likes tea.",
            confidence=0.9,
            observed_at="2026-04-21T10:00:00Z",
            source_id=source_id,
            quote_text="Alice likes tea.",
        )
        fact = service.add_fact(conn, payload)

    assert fact["domain"] == "preferences"
    assert fact["payload"]["value"] == "tea"
    assert len(fact["evidence"]) == 1


def test_add_fact_merges_duplicate_evidence_and_preserves_locator(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/note-dup.md",
            source_type="note",
            origin_uri="/tmp/note-dup.md",
            title="note-dup",
            sha256="abc124",
            parsed_text="Alice likes tea.",
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text="Alice likes tea.")
        chunk_id = conn.execute(
            "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
            (source_id,),
        ).fetchone()["id"]
        payload = MemoryFactInput(
            workspace="default",
            person_id=int(person["id"]),
            domain="preferences",
            category="food_drink",
            canonical_key="alice:preferences:drink.favorite:tea",
            payload={"value": "tea"},
            summary="Alice likes tea.",
            confidence=0.9,
            observed_at="2026-04-21T10:00:00Z",
            source_id=source_id,
            quote_text="Alice likes tea.",
        )
        first = service.add_fact(conn, payload, locator={"message_ids": ["1"]}, source_chunk_id=int(chunk_id))
        second = service.add_fact(conn, payload, locator={"message_ids": ["2"]}, source_chunk_id=int(chunk_id))

    assert first["id"] == second["id"]
    assert len(second["evidence"]) == 2
    assert second["evidence"][0]["locator_json"]["message_ids"] == ["1"]
    assert second["evidence"][1]["locator_json"]["message_ids"] == ["2"]
    assert second["evidence"][0]["source_segment_id"] is not None
    assert second["evidence"][1]["source_segment_id"] is not None


def test_residence_value_conflict_supersedes_previous_current_fact(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/residence-conflict.md",
            source_type="note",
            origin_uri="/tmp/residence-conflict.md",
            title="residence-conflict",
            sha256="residence-conflict-sha",
            parsed_text="Alice lived in Berlin and later moved to Lisbon.",
        )
        berlin = service.add_fact(
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
        lisbon = service.add_fact(
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
        berlin = fact_repo.get_fact(conn, fact_id=int(berlin["id"]))
        lisbon = fact_repo.get_fact(conn, fact_id=int(lisbon["id"]))

    assert berlin["status"] == "superseded"
    assert lisbon["status"] == "active"
    assert lisbon["supersedes_fact_id"] == berlin["id"]


def test_preference_polarity_conflict_supersedes_previous_preference(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/preference-conflict.md",
            source_type="note",
            origin_uri="/tmp/preference-conflict.md",
            title="preference-conflict",
            sha256="preference-conflict-sha",
            parsed_text="Alice liked tea and later disliked tea.",
        )
        like_fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea:like",
                payload={"value": "tea", "polarity": "like", "strength": "medium", "reason": "", "is_current": True},
                summary="Alice likes tea.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice liked tea.",
            ),
        )
        dislike_fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea:dislike",
                payload={"value": "tea", "polarity": "dislike", "strength": "medium", "reason": "", "is_current": True},
                summary="Alice dislikes tea.",
                confidence=0.92,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice later disliked tea.",
            ),
        )
        like_fact = fact_repo.get_fact(conn, fact_id=int(like_fact["id"]))
        dislike_fact = fact_repo.get_fact(conn, fact_id=int(dislike_fact["id"]))

    assert like_fact["status"] == "superseded"
    assert dislike_fact["status"] == "active"
    assert dislike_fact["supersedes_fact_id"] == like_fact["id"]


def test_temporal_conflict_inserts_historical_fact_without_replacing_current(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()
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
            source_path="var/raw/temporal-conflict.md",
            source_type="note",
            origin_uri="/tmp/temporal-conflict.md",
            title="temporal-conflict",
            sha256="temporal-conflict-sha",
            parsed_text="Alice lives in Lisbon now and previously lived in Berlin.",
        )
        current_fact = service.add_fact(
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
                quote_text="Alice lives in Lisbon now.",
            ),
        )
        historical_fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Alice lived in Berlin.",
                confidence=0.88,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice previously lived in Berlin.",
            ),
        )
        current = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )
        history = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where did Alice live before Lisbon?", temporal_mode="history"),
        )

    assert current_fact["status"] == "active"
    assert historical_fact["status"] == "superseded"
    assert historical_fact["superseded_by_fact_id"] == current_fact["id"]
    assert current.hits[0].payload["city"] == "Lisbon"
    assert any(hit.payload["city"] == "Berlin" for hit in history.hits)


def test_event_fact_persists_event_at_without_validity_window(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/event-time.md",
            source_type="note",
            origin_uri="/tmp/event-time.md",
            title="event-time",
            sha256="event-time-sha",
            parsed_text="Alice attended PyCon in 2025.",
        )
        fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon",
                payload={"event": "PyCon"},
                summary="Alice attended PyCon.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                event_at="2025",
                source_id=source_id,
                quote_text="Alice attended PyCon in 2025.",
            ),
        )

    assert fact["observed_at"] == "2026-04-21T10:00:00Z"
    assert fact["event_at"] == "2025"
    assert fact["valid_from"] == ""
    assert fact["valid_to"] == ""

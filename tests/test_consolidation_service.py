from __future__ import annotations

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


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

from __future__ import annotations

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def test_person_alias_upsert_rebinds_alias_resolution(settings):
    repository = FactRepository()

    with get_connection(settings.db_path) as conn:
        alice = repository.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        maria = repository.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Maria",
            slug="maria",
            person_type="human",
            aliases=["Maria"],
        )
        repository.upsert_person_alias(
            conn,
            workspace_slug="default",
            person_id=int(maria["id"]),
            alias="A. Example",
        )
        resolved = repository.resolve_person_id(
            conn,
            workspace_slug="default",
            person_slug="maria",
        )
        alias_person = conn.execute(
            """
            SELECT person_id
            FROM person_aliases
            WHERE normalized_alias = 'a. example'
            """,
        ).fetchone()

    assert resolved == int(maria["id"])
    assert alias_person["person_id"] == int(maria["id"])
    assert int(alice["id"]) != int(maria["id"])


def test_person_merge_moves_facts_and_marks_source_person_merged(settings):
    repository = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()

    with get_connection(settings.db_path) as conn:
        alice = repository.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        maria = repository.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Maria",
            slug="maria",
            person_type="human",
            aliases=["Maria"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/person-merge.md",
            source_type="note",
            origin_uri="/tmp/person-merge.md",
            title="person-merge",
            sha256="person-merge-sha",
            parsed_text="Maria lives in Lisbon.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(maria["id"]),
                domain="biography",
                category="residence",
                canonical_key="maria:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Maria lives in Lisbon.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Maria lives in Lisbon.",
            ),
        )
        merge = repository.merge_persons(
            conn,
            workspace_slug="default",
            from_person_id=int(maria["id"]),
            to_person_id=int(alice["id"]),
            reason="same person",
        )
        alice_facts = repository.list_facts(conn, workspace_slug="default", person_id=int(alice["id"]))
        maria_person = repository.get_person(conn, workspace_slug="default", person_id=int(maria["id"]))

    assert merge["from_person_id"] == int(maria["id"])
    assert merge["to_person_id"] == int(alice["id"])
    assert any(fact["summary"] == "Maria lives in Lisbon." for fact in alice_facts)
    assert maria_person is not None
    assert maria_person["status"] == "merged"

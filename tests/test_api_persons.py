from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def test_api_person_alias_and_list(monkeypatch, settings):
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        person = repository.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    alias = client.post(
        "/v1/persons/aliases/upsert",
        json={"workspace": "default", "person_id": person["id"], "alias": "A. Example"},
    )
    assert alias.status_code == 200
    assert alias.json()["normalized_alias"] == "a. example"

    listed = client.post("/v1/persons/list", json={"workspace": "default"})
    assert listed.status_code == 200
    assert any(item["slug"] == "alice" for item in listed.json()["items"])


def test_api_person_merge_moves_fact_ownership(monkeypatch, settings):
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
            source_path="var/raw/api-person-merge.md",
            source_type="note",
            origin_uri="/tmp/api-person-merge.md",
            title="api-person-merge",
            sha256="api-person-merge-sha",
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

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    merge = client.post(
        "/v1/persons/merge",
        json={"workspace": "default", "from_person_slug": "maria", "to_person_slug": "alice", "reason": "same person"},
    )
    assert merge.status_code == 200

    facts = client.post("/v1/facts/list", json={"workspace": "default"})
    assert facts.status_code == 200
    assert any(item["person_id"] == alice["id"] and item["summary"] == "Maria lives in Lisbon." for item in facts.json()["items"])

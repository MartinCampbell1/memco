from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _actor(*, person_ids=None, domains=None):
    return {
        "actor_id": "dev-owner",
        "actor_type": "owner",
        "allowed_person_ids": person_ids or [],
        "allowed_domains": domains or [],
        "can_view_sensitive": True,
    }


def _seed_fact(settings, *, person_slug: str, display_name: str, domain: str, category: str, canonical_key: str, payload: dict, summary: str):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name=display_name,
            slug=person_slug,
            person_type="human",
            aliases=[display_name],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path=f"var/raw/{person_slug}-{domain}-{category}.md",
            source_type="note",
            origin_uri=f"/tmp/{person_slug}-{domain}-{category}.md",
            title=f"{person_slug}-{domain}-{category}",
            sha256=f"{person_slug}-{domain}-{category}-sha",
            parsed_text=summary,
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain=domain,
                category=category,
                canonical_key=canonical_key,
                payload=payload,
                summary=summary,
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=summary,
            ),
        )
    return int(person["id"])


def test_actor_required_in_actor_scoped_mode(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?"},
    )
    chat = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?"},
    )

    assert retrieve.status_code == 422
    assert "Actor context is required" in retrieve.json()["detail"]
    assert chat.status_code == 422
    assert "Actor context is required" in chat.json()["detail"]


def test_actor_allowed_person_ids_filter_retrieve(monkeypatch, settings):
    _alice_id = _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="residence",
        canonical_key="alice:biography:residence:lisbon",
        payload={"city": "Lisbon"},
        summary="Alice lives in Lisbon.",
    )
    _bob_id = _seed_fact(
        settings,
        person_slug="bob",
        display_name="Bob",
        domain="biography",
        category="residence",
        canonical_key="bob:biography:residence:porto",
        payload={"city": "Porto"},
        summary="Bob lives in Porto.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "Where does Alice live?",
            "actor": _actor(person_ids=[999999]),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["hits"] == []
    assert payload["support_level"] == "none"
    assert payload["unsupported_premise_detected"] is True


def test_actor_allowed_domains_filter_chat(monkeypatch, settings):
    _alice_id = _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="work",
        category="employment",
        canonical_key="alice:work:employment:software-engineer",
        payload={"title": "software engineer"},
        summary="Alice works as software engineer.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "What does Alice do for work?",
            "actor": _actor(domains=["biography"]),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["retrieval"]["hits"] == []
    assert payload["retrieval"]["support_level"] == "none"

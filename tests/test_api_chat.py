from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _actor(**overrides):
    payload = {
        "actor_id": "dev-owner",
        "actor_type": "owner",
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": True,
    }
    payload.update(overrides)
    return payload


def test_chat_returns_refusal_without_memory(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor()},
    )

    assert response.status_code == 200
    assert response.json()["refused"] is True
    assert response.json()["answer"] == "I don't have confirmed memory evidence for that."


def test_chat_returns_answer_with_memory(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice.md",
            source_type="note",
            origin_uri="/tmp/alice.md",
            title="alice",
            sha256="ghi789",
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
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is False
    assert "Lisbon" in payload["answer"]


def test_chat_returns_partial_support_without_hallucinating(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-partial-chat.md",
            source_type="note",
            origin_uri="/tmp/alice-partial-chat.md",
            title="alice-partial-chat",
            sha256="ghi790",
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
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "Does Alice live in Lisbon and work at Stripe?",
            "actor": _actor(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is False
    assert "Lisbon" in payload["answer"]
    assert "Stripe" in payload["answer"]
    assert payload["retrieval"]["support_level"] == "partial"


def test_chat_ignores_style_and_psychometrics_for_factual_answers(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-style.md",
            source_type="note",
            origin_uri="/tmp/alice-style.md",
            title="alice-style",
            sha256="ghi791",
            parsed_text="Haha, I am curious.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="style",
                category="communication_style",
                canonical_key="alice:style:communication_style:humorous",
                payload={"tone": "humorous", "generation_guidance": "Use light humor."},
                summary="Alice often communicates humorously.",
                source_kind="explicit",
                confidence=0.6,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Haha",
            ),
            locator={"message_ids": ["1"]},
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Does Alice own a cat?", "actor": _actor()},
    )

    assert response.status_code == 200
    assert response.json()["refused"] is True

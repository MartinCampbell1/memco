from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _actor(settings, **overrides):
    actor_id = overrides.get("actor_id", "dev-owner")
    policy = settings.api.actor_policies[actor_id]
    payload = {
        "actor_id": actor_id,
        "actor_type": policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": policy.can_view_sensitive,
    }
    payload.update(overrides)
    return payload


def _seed_fact(settings, *, domain: str, category: str, canonical_key: str, payload: dict, summary: str, quote: str) -> int:
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
            source_path=f"var/raw/{canonical_key}.md",
            source_type="note",
            origin_uri=f"/tmp/{canonical_key}.md",
            title=canonical_key,
            sha256=canonical_key,
            parsed_text=quote,
        )
        fact = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain=domain,
                category=category,
                canonical_key=canonical_key,
                payload=payload,
                summary=summary,
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=quote,
            ),
        )
    return int(fact["id"])


def test_agent_memory_context_returns_structured_context_without_chat_answer(monkeypatch, settings):
    fact_id = _seed_fact(
        settings,
        domain="biography",
        category="residence",
        canonical_key="alice:biography:residence:lisbon",
        payload={"city": "Lisbon"},
        summary="Alice lives in Lisbon.",
        quote="Alice lives in Lisbon.",
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/agent/memory-context",
        json={
            "person_slug": "alice",
            "query": "Where does Alice live?",
            "mode": "retrieval_only",
            "max_facts": 10,
            "include_evidence": True,
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "retrieval_only"
    assert payload["answerable"] is True
    assert payload["support_level"] == "supported"
    assert "answer" not in payload
    assert payload["memory_context"] == [
        {
            "fact_id": fact_id,
            "domain": "biography",
            "category": "residence",
            "summary": "Alice lives in Lisbon.",
            "status": "active",
            "confidence": 0.9,
            "observed_at": "2026-04-21T10:00:00Z",
            "valid_from": "2026-04-21T10:00:00Z",
            "valid_to": "",
            "event_at": "",
            "evidence": payload["memory_context"][0]["evidence"],
        }
    ]
    assert payload["memory_context"][0]["evidence"][0]["quote_text"] == "Alice lives in Lisbon."
    assert "Use only memory_context facts for personal claims." in payload["instructions_for_agent"]
    assert "If a required fact is absent, say unknown." in payload["instructions_for_agent"]


def test_agent_memory_context_respects_max_facts_and_evidence_toggle(monkeypatch, settings):
    _seed_fact(
        settings,
        domain="work",
        category="tool",
        canonical_key="alice:work:tool:python",
        payload={"tool": "Python"},
        summary="Alice uses Python.",
        quote="Alice uses Python.",
    )
    _seed_fact(
        settings,
        domain="work",
        category="tool",
        canonical_key="alice:work:tool:postgres",
        payload={"tool": "Postgres"},
        summary="Alice uses Postgres.",
        quote="Alice uses Postgres.",
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/agent/memory-context",
        json={
            "person_slug": "alice",
            "query": "What tools does Alice use?",
            "mode": "retrieval_only",
            "max_facts": 1,
            "include_evidence": False,
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["memory_context"]) == 1
    assert "evidence" not in payload["memory_context"][0]


def test_agent_memory_context_refuses_absent_memory_without_fallback(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/agent/memory-context",
        json={
            "person_slug": "alice",
            "query": "Where does Alice live?",
            "mode": "retrieval_only",
            "max_facts": 10,
            "include_evidence": True,
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answerable"] is False
    assert payload["support_level"] == "unsupported"
    assert payload["must_not_use_as_fact"] is True
    assert payload["memory_context"] == []
    assert "If a required fact is absent, say unknown." in payload["instructions_for_agent"]

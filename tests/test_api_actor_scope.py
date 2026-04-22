from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _actor(settings, *, actor_id="dev-owner", person_ids=None, domains=None, actor_type=None, can_view_sensitive=None):
    policy = settings.api.actor_policies.get(actor_id)
    if policy is None:
        resolved_actor_type = actor_type or "owner"
        resolved_can_view_sensitive = False if can_view_sensitive is None else can_view_sensitive
        return {
            "actor_id": actor_id,
            "actor_type": resolved_actor_type,
            "auth_token": "forged-token",
            "allowed_person_ids": person_ids or [],
            "allowed_domains": domains or [],
            "can_view_sensitive": resolved_can_view_sensitive,
        }
    return {
        "actor_id": actor_id,
        "actor_type": actor_type or policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": person_ids or [],
        "allowed_domains": domains or [],
        "can_view_sensitive": policy.can_view_sensitive if can_view_sensitive is None else can_view_sensitive,
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


def test_actor_required_on_public_retrieve_and_chat_even_without_env_toggle(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.delenv("MEMCO_REQUIRE_ACTOR_SCOPE", raising=False)
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
            "actor": _actor(settings, person_ids=[999999]),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["hits"] == []
    assert payload["support_level"] == "unsupported"
    assert payload["unsupported_premise_detected"] is True


def test_retrieve_supports_core_only_detail_policy(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="residence",
        canonical_key="alice:biography:residence:lisbon",
        payload={"city": "Lisbon"},
        summary="Alice lives in Lisbon.",
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
            "detail_policy": "core_only",
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["detail_policy"] == "core_only"
    assert payload["hits"] == [
        {
            "fact_id": payload["hits"][0]["fact_id"],
            "domain": "biography",
            "category": "residence",
            "summary": "Alice lives in Lisbon.",
            "status": "active",
            "confidence": 0.95,
        }
    ]


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
            "actor": _actor(settings, domains=["biography"]),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["retrieval"]["hits"] == []
    assert payload["retrieval"]["support_level"] == "unsupported"


def test_sensitive_fact_visible_to_owner_with_sensitive_access(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="family",
        canonical_key="alice:biography:family:sister:emma",
        payload={"relation": "sister", "name": "Emma"},
        summary="Alice's sister is Emma.",
    )
    with get_connection(settings.db_path) as conn:
        row = conn.execute(
            "SELECT sensitivity, visibility FROM memory_facts WHERE canonical_key = ?",
            ("alice:biography:family:sister:emma",),
        ).fetchone()

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "biography",
            "category": "family",
            "query": "Who is in Alice's family?",
            "actor": _actor(settings, actor_type="owner", can_view_sensitive=True),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert row is not None
    assert row["sensitivity"] == "high"
    assert row["visibility"] == "owner_only"
    assert len(payload["hits"]) == 1
    assert payload["hits"][0]["payload"]["name"] == "Emma"


def test_sensitive_fact_cannot_be_fetched_anonymously(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="family",
        canonical_key="alice:biography:family:sister:emma",
        payload={"relation": "sister", "name": "Emma"},
        summary="Alice's sister is Emma.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.delenv("MEMCO_REQUIRE_ACTOR_SCOPE", raising=False)
    client = TestClient(app)

    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "biography",
            "category": "family",
            "query": "Who is in Alice's family?",
        },
    )

    assert response.status_code == 422
    assert "Actor context is required" in response.json()["detail"]


def test_sensitive_fact_hidden_from_admin_in_normal_retrieval(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="family",
        canonical_key="alice:biography:family:sister:emma",
        payload={"relation": "sister", "name": "Emma"},
        summary="Alice's sister is Emma.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "biography",
            "category": "family",
            "query": "Who is in Alice's family?",
            "actor": _actor(settings, actor_id="maintenance-admin", actor_type="admin", can_view_sensitive=True),
        },
    )

    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]


def test_sensitive_fact_hidden_when_owner_disables_sensitive_access(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="family",
        canonical_key="alice:biography:family:sister:emma",
        payload={"relation": "sister", "name": "Emma"},
        summary="Alice's sister is Emma.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "biography",
            "category": "family",
            "query": "Who is in Alice's family?",
            "actor": _actor(settings, actor_type="owner", can_view_sensitive=False),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["retrieval"]["hits"] == []


def test_sensitive_fact_hidden_from_eval_actor(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="family",
        canonical_key="alice:biography:family:sister:emma",
        payload={"relation": "sister", "name": "Emma"},
        summary="Alice's sister is Emma.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "biography",
            "category": "family",
            "query": "Who is in Alice's family?",
            "actor": _actor(settings, actor_id="eval-runner", actor_type="eval", can_view_sensitive=True),
        },
    )

    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]


def test_forged_owner_actor_is_rejected_server_side(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="family",
        canonical_key="alice:biography:family:sister:emma",
        payload={"relation": "sister", "name": "Emma"},
        summary="Alice's sister is Emma.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/retrieve",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "domain": "biography",
            "category": "family",
            "query": "Who is in Alice's family?",
            "actor": _actor(settings, actor_id="forged-owner", actor_type="owner", can_view_sensitive=True),
        },
    )

    assert response.status_code == 403
    assert "Unknown actor" in response.json()["detail"]


def test_admin_cannot_use_normal_retrieve_path(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="residence",
        canonical_key="alice:biography:residence:lisbon",
        payload={"city": "Lisbon"},
        summary="Alice lives in Lisbon.",
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
            "actor": _actor(settings, actor_id="maintenance-admin", actor_type="admin", can_view_sensitive=True),
        },
    )

    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]


def test_eval_cannot_use_normal_chat_path(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="residence",
        canonical_key="alice:biography:residence:lisbon",
        payload={"city": "Lisbon"},
        summary="Alice lives in Lisbon.",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "Where does Alice live?",
            "actor": _actor(settings, actor_id="eval-runner", actor_type="eval", can_view_sensitive=True),
        },
    )

    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]


def test_admin_can_use_explicit_review_maintenance_path(monkeypatch, settings):
    _seed_fact(
        settings,
        person_slug="alice",
        display_name="Alice",
        domain="biography",
        category="residence",
        canonical_key="alice:biography:residence:lisbon",
        payload={"city": "Lisbon"},
        summary="Alice lives in Lisbon.",
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    monkeypatch.setenv("MEMCO_REQUIRE_ACTOR_SCOPE", "true")
    client = TestClient(app)

    response = client.post(
        "/v1/review/list",
        json={
            "workspace": "default",
            "status": "pending",
            "actor": _actor(settings, actor_id="maintenance-admin", actor_type="admin", can_view_sensitive=False),
        },
    )

    assert response.status_code == 200
    assert "items" in response.json()

from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _owner_actor(settings):
    policy = settings.api.actor_policies["dev-owner"]
    return {
        "actor_id": "dev-owner",
        "actor_type": policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": policy.can_view_sensitive,
    }


def _seed_persona(settings):
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
            source_path="var/raw/export-seed.md",
            source_type="note",
            origin_uri="/tmp/export-seed.md",
            title="export-seed",
            sha256="export-seed-sha",
            parsed_text="Alice lives in Lisbon. Alice likes tea.",
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
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea",
                payload={"value": "tea", "polarity": "like", "strength": "medium", "reason": "", "is_current": True},
                summary="Alice likes tea.",
                confidence=0.9,
                observed_at="2026-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Alice likes tea.",
            ),
        )
    return int(person["id"])


def test_api_persona_export_returns_structured_json_without_raw_content(monkeypatch, settings):
    _seed_persona(settings)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/persona/export",
        json={"workspace": "default", "person_slug": "alice", "actor": _owner_actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_type"] == "persona_export"
    assert payload["person"]["slug"] == "alice"
    assert payload["counts"]["fact_count"] == 2
    assert payload["counts"]["source_count"] == 1
    assert "biography" in payload["domains"]
    assert "preferences" in payload["domains"]
    dumped = str(payload)
    assert "parsed_text" not in dumped
    assert "source_path" not in dumped
    assert "origin_uri" not in dumped
    assert "quote_text" not in dumped


def test_api_persona_export_supports_domain_filter(monkeypatch, settings):
    _seed_persona(settings)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/persona/export",
        json={"workspace": "default", "person_slug": "alice", "domain": "biography", "actor": _owner_actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["domains"].keys()) == {"biography"}
    assert payload["counts"]["domain_counts"] == {"biography": 1}


def test_api_persona_export_supports_core_only_detail_policy(monkeypatch, settings):
    _seed_persona(settings)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/persona/export",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "detail_policy": "core_only",
            "actor": _owner_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    fact = payload["domains"]["biography"]["residence"][0]
    assert payload["filters"]["detail_policy"] == "core_only"
    assert "payload" not in fact
    assert "evidence_summary" not in fact


def test_api_persona_export_supports_exhaustive_detail_policy(monkeypatch, settings):
    _seed_persona(settings)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/persona/export",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "detail_policy": "exhaustive",
            "actor": _owner_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    fact = payload["domains"]["biography"]["residence"][0]
    assert payload["filters"]["detail_policy"] == "exhaustive"
    assert fact["evidence"][0]["evidence_id"] >= 1
    assert "quote_text" not in str(fact["evidence"][0])

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.services.ingest_service import IngestService


def _maintenance_actor(settings):
    policy = settings.api.actor_policies["maintenance-admin"]
    return {
        "actor_id": "maintenance-admin",
        "actor_type": policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": policy.can_view_sensitive,
    }


def test_api_ingest_conversation_route(monkeypatch, settings, tmp_path):
    source = tmp_path / "api-conversation.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I live in Berlin."},
                    {"speaker": "Bob", "timestamp": "2026-04-21T10:01:00Z", "text": "I prefer tea."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with get_connection(settings.db_path) as conn:
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/conversation",
        json={
            "workspace": "default",
            "source_id": imported.source_id,
            "conversation_uid": "main",
            "title": "API Conversation",
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == imported.source_id
    assert payload["session_count"] == 1
    assert payload["message_count"] == 2
    assert payload["chunk_count"] >= 1


def test_api_ingest_text_route(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/text",
        json={
            "workspace": "default",
            "source_type": "note",
            "title": "inline",
            "text": "Alice lives in Lisbon.",
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_type"] == "note"


def test_api_ingest_pipeline_route_happy_path(monkeypatch, settings, tmp_path):
    source = tmp_path / "api-pipeline.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/pipeline",
        json={
            "workspace": "default",
            "path": str(source),
            "source_type": "json",
            "person_display_name": "Alice",
            "person_slug": "alice",
            "aliases": ["Alice"],
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["person"]["slug"] == "alice"
    assert payload["conversation"]["conversation_id"] >= 1
    assert payload["published"][0]["fact"]["payload"]["city"] == "Lisbon"
    assert payload["pending_review_items"] == []


def test_api_ingest_pipeline_owner_fallback_for_speakerless_note(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/pipeline",
        json={
            "workspace": "default",
            "text": "I live in Lisbon. I work as a designer.",
            "source_type": "note",
            "title": "alice-note",
            "person_display_name": "Alice",
            "person_slug": "alice",
            "aliases": ["Alice"],
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["person"]["slug"] == "alice"
    assert payload["needs_review_candidate_ids"] == []
    assert payload["pending_review_items"] == []
    assert len(payload["published"]) == 2
    facts = {item["fact"]["domain"]: item["fact"] for item in payload["published"]}
    assert facts["biography"]["payload"]["city"] == "Lisbon"
    assert facts["work"]["payload"]["title"] == "designer"
    for item in payload["published"]:
        candidate = item["candidate"]
        fact = item["fact"]
        assert candidate["person_id"] == payload["person"]["id"]
        assert candidate["payload"]["attribution_method"] == "owner_first_person_fallback"
        assert candidate["payload"]["attribution_confidence"] == 0.96
        assert candidate["payload"]["source_type"] == "note"
        assert candidate["evidence"][0]["attribution_method"] == "owner_first_person_fallback"
        assert fact["person_id"] == payload["person"]["id"]
        assert fact["payload"]["attribution_method"] == "owner_first_person_fallback"
        assert fact["evidence"][0]["locator_json"]["attribution_method"] == "owner_first_person_fallback"
        assert fact["evidence"][0]["locator_json"]["attribution_confidence"] == 0.96
        assert fact["evidence"][0]["locator_json"]["source_type"] == "note"


def test_api_ingest_pipeline_owner_fallback_for_multi_message_speakerless_json(
    monkeypatch,
    settings,
    tmp_path,
):
    source = tmp_path / "speakerless-owner.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"timestamp": "2026-01-01T10:00:00Z", "text": "I live in Lisbon."},
                    {"timestamp": "2026-01-01T10:01:00Z", "text": "I work as a designer."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/pipeline",
        json={
            "workspace": "default",
            "path": str(source),
            "source_type": "json",
            "person_display_name": "Alice",
            "person_slug": "alice",
            "aliases": ["Alice"],
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["extracted_total"] == 2
    assert payload["needs_review_candidate_ids"] == []
    assert len(payload["published"]) == 2
    facts = {item["fact"]["domain"]: item["fact"] for item in payload["published"]}
    assert facts["biography"]["payload"]["city"] == "Lisbon"
    assert facts["work"]["payload"]["title"] == "designer"
    for item in payload["published"]:
        assert item["candidate"]["person_id"] == payload["person"]["id"]
        assert item["candidate"]["payload"]["attribution_method"] == "owner_first_person_fallback"
        assert item["fact"]["evidence"][0]["locator_json"]["attribution_method"] == "owner_first_person_fallback"
        assert item["fact"]["evidence"][0]["locator_json"]["source_type"] == "json"


def test_api_ingest_pipeline_keeps_ambiguous_speakerless_note_for_review(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/pipeline",
        json={
            "workspace": "default",
            "text": "I live in Lisbon. Bob works as a designer.",
            "source_type": "note",
            "title": "ambiguous-note",
            "person_display_name": "Alice",
            "person_slug": "alice",
            "aliases": ["Alice"],
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["published"] == []
    assert payload["validated_candidate_ids"] == []
    assert payload["needs_review_candidate_ids"] != []
    assert payload["pending_review_items"] != []
    review_candidate = payload["pending_review_items"][0]["candidate"]
    assert review_candidate["person_id"] is None
    assert "speaker_unresolved" in review_candidate["reason"]
    assert "attribution_method" not in review_candidate["payload"]


def test_api_ingest_pipeline_route_reports_pending_review_items(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/ingest/pipeline",
        json={
            "workspace": "default",
            "text": "Guest: Bob is my friend.",
            "source_type": "text",
            "title": "inline-review",
            "actor": _maintenance_actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["published"] == []
    assert payload["pending_review_items"] != []

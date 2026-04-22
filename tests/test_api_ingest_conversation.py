from __future__ import annotations

import json

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.services.ingest_service import IngestService


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
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == imported.source_id
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
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["person"]["slug"] == "alice"
    assert payload["conversation"]["conversation_id"] >= 1
    assert payload["published"][0]["fact"]["payload"]["city"] == "Lisbon"
    assert payload["pending_review_items"] == []


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
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["published"] == []
    assert payload["pending_review_items"] != []

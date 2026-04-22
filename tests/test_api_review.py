from __future__ import annotations

import json

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.repositories.fact_repository import FactRepository
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.ingest_service import IngestService


def _actor(settings, **overrides):
    actor_id = overrides.get("actor_id", "dev-owner")
    policy = settings.api.actor_policies[actor_id]
    return {
        "actor_id": actor_id,
        "actor_type": policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": policy.can_view_sensitive,
        **overrides,
    }


def _seed_review_conversation(settings, tmp_path):
    source = tmp_path / "review-api.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Guest", "timestamp": "2026-04-21T10:00:00Z", "text": "Bob is my friend."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        alice = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
    return conversation.conversation_id, int(alice["id"])


def test_api_review_list_and_resolve(monkeypatch, settings, tmp_path):
    conversation_id, alice_id = _seed_review_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    extract = client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    assert extract.status_code == 200

    review_list = client.post(
        "/v1/review/list",
        json={"workspace": "default", "status": "pending", "actor": _actor(settings, actor_id="maintenance-admin")},
    )
    assert review_list.status_code == 200
    items = review_list.json()["items"]
    assert len(items) >= 1
    queue_item = items[0]

    resolve = client.post(
        "/v1/review/resolve",
        json={
            "queue_id": queue_item["id"],
            "decision": "approved",
            "reason": "checked",
            "candidate_person_id": alice_id,
            "actor": _actor(settings, actor_id="maintenance-admin"),
        },
    )
    assert resolve.status_code == 200
    payload = resolve.json()
    assert payload["status"] == "approved"
    assert payload["candidate"]["candidate_status"] == "validated_candidate"
    assert payload["decision_summary"].startswith("approved")


def test_api_review_resolution_then_publish_enables_retrieval(monkeypatch, settings, tmp_path):
    conversation_id, alice_id = _seed_review_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    queue_item = client.post(
        "/v1/review/list",
        json={"workspace": "default", "status": "pending", "actor": _actor(settings, actor_id="maintenance-admin")},
    ).json()["items"][0]
    with get_connection(settings.db_path) as conn:
        bob_id = FactRepository().resolve_person_id(conn, workspace_slug="default", person_slug="bob")
    resolved = client.post(
        "/v1/review/resolve",
        json={
            "queue_id": queue_item["id"],
            "decision": "approved",
            "reason": "checked",
            "candidate_person_id": alice_id,
            "candidate_target_person_id": bob_id,
            "actor": _actor(settings, actor_id="maintenance-admin"),
        },
    ).json()

    publish = client.post(
        "/v1/candidates/publish",
        json={"workspace": "default", "candidate_id": resolved["candidate"]["id"], "actor": _actor(settings)},
    )
    assert publish.status_code == 200

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Who is Alice friends with?", "domain": "social_circle", "actor": _actor(settings)},
    )
    assert retrieve.status_code == 200
    assert len(retrieve.json()["hits"]) == 1


def test_api_review_list_exposes_operator_summary_fields(monkeypatch, settings, tmp_path):
    conversation_id, _alice_id = _seed_review_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    review_list = client.post(
        "/v1/review/list",
        json={"workspace": "default", "status": "pending", "actor": _actor(settings, actor_id="maintenance-admin")},
    )

    assert review_list.status_code == 200
    item = review_list.json()["items"][0]
    assert "candidate_summary" in item
    assert "candidate_domain" in item
    assert "candidate_reason" in item


def test_api_review_rejected_candidate_cannot_be_published(monkeypatch, settings, tmp_path):
    conversation_id, _alice_id = _seed_review_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    queue_item = client.post(
        "/v1/review/list",
        json={"workspace": "default", "status": "pending", "actor": _actor(settings, actor_id="maintenance-admin")},
    ).json()["items"][0]
    resolved = client.post(
        "/v1/review/resolve",
        json={
            "queue_id": queue_item["id"],
            "decision": "rejected",
            "reason": "bad relation",
            "actor": _actor(settings, actor_id="maintenance-admin"),
        },
    )
    assert resolved.status_code == 200
    candidate_id = resolved.json()["candidate"]["id"]

    with get_connection(settings.db_path) as conn:
        from memco.services.publish_service import PublishService

        service = PublishService()
        try:
            service.publish_candidate(conn, workspace_slug="default", candidate_id=int(candidate_id))
            raised = False
        except ValueError:
            raised = True
    assert raised is True


def test_api_review_rejects_invalid_decision(monkeypatch, settings, tmp_path):
    conversation_id, _alice_id = _seed_review_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    queue_item = client.post(
        "/v1/review/list",
        json={"workspace": "default", "status": "pending", "actor": _actor(settings, actor_id="maintenance-admin")},
    ).json()["items"][0]

    response = client.post(
        "/v1/review/resolve",
        json={
            "queue_id": queue_item["id"],
            "decision": "maybe",
            "reason": "invalid",
            "actor": _actor(settings, actor_id="maintenance-admin"),
        },
    )

    assert response.status_code == 422

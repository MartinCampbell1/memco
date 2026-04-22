from __future__ import annotations

import json

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.ingest_service import IngestService
from memco.services.conversation_ingest_service import ConversationIngestService


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


def _seed_conversation(settings, tmp_path):
    source = tmp_path / "api-candidates.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:01:00Z", "text": "I like tea."},
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:02:00Z", "text": "Bob is my friend."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
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
    return conversation.conversation_id


def _seed_publish_candidate(
    settings,
    *,
    workspace: str = "default",
    domain: str = "biography",
    category: str = "residence",
    canonical_key: str = "alice:biography:residence:lisbon",
    payload: dict | None = None,
    summary: str = "Alice lives in Lisbon.",
    confidence: float = 0.91,
    candidate_status: str = "validated_candidate",
):
    payload = payload or {"city": "Lisbon"}
    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        candidate_repo = CandidateRepository()
        source_repo = SourceRepository()
        alice = fact_repo.upsert_person(
            conn,
            workspace_slug=workspace,
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        fact_repo.upsert_person(
            conn,
            workspace_slug=workspace,
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug=workspace,
            source_path=f"var/raw/{workspace}-publish-api.md",
            source_type="note",
            origin_uri=f"/tmp/{workspace}-publish-api.md",
            title=f"{workspace}-publish-api",
            sha256=f"{workspace}-publish-api-sha",
            parsed_text=summary,
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text=summary)
        chunk_id = conn.execute(
            "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
            (source_id,),
        ).fetchone()["id"]
        source_segment_id = source_repo.get_segment_by_chunk_id(conn, chunk_id=int(chunk_id))["id"]
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug=workspace,
            person_id=int(alice["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=int(chunk_id),
            domain=domain,
            category=category,
            subcategory="",
            canonical_key=canonical_key,
            payload=payload,
            summary=summary,
            confidence=confidence,
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=[
                {
                    "quote": summary,
                    "message_ids": ["1"],
                    "source_segment_ids": [int(source_segment_id)],
                    "chunk_kind": "conversation",
                }
            ],
        )
        if candidate_status != "extracted_candidate":
            candidate = candidate_repo.mark_candidate_status(
                conn,
                candidate_id=int(candidate["id"]),
                candidate_status=candidate_status,
            )
    return int(candidate["id"])


def test_api_candidate_extract_list_publish_and_reject(monkeypatch, settings, tmp_path):
    conversation_id = _seed_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    extract = client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    assert extract.status_code == 200
    items = extract.json()["items"]
    assert len(items) >= 3

    listed = client.post(
        "/v1/candidates/list",
        json={"workspace": "default", "candidate_status": "validated_candidate", "actor": _actor(settings, actor_id="maintenance-admin")},
    )
    assert listed.status_code == 200
    listed_items = listed.json()["items"]
    biography = next(item for item in listed_items if item["domain"] == "biography")

    publish = client.post(
        "/v1/candidates/publish",
        json={"workspace": "default", "candidate_id": biography["id"], "actor": _actor(settings)},
    )
    assert publish.status_code == 200
    assert publish.json()["candidate"]["candidate_status"] == "published"

    review_items = client.post(
        "/v1/candidates/list",
        json={"workspace": "default", "candidate_status": "needs_review", "actor": _actor(settings, actor_id="maintenance-admin")},
    )
    assert review_items.status_code == 200
    social = next(item for item in review_items.json()["items"] if item["domain"] == "social_circle")

    reject = client.post(
        "/v1/candidates/reject",
        json={"candidate_id": social["id"], "reason": "target unresolved", "actor": _actor(settings, actor_id="maintenance-admin")},
    )
    assert reject.status_code == 200
    assert reject.json()["candidate_status"] == "rejected"


def test_api_candidate_extract_is_idempotent(monkeypatch, settings, tmp_path):
    conversation_id = _seed_conversation(settings, tmp_path)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    first = client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )
    second = client.post(
        "/v1/candidates/extract",
        json={"workspace": "default", "conversation_id": conversation_id, "actor": _actor(settings)},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [item["id"] for item in second.json()["items"]]


def test_api_candidate_extract_can_include_style_and_psychometrics(monkeypatch, settings, tmp_path):
    source = tmp_path / "api-candidates-style.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "Haha, I'm very curious and I appreciate your help."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
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
    conversation_id = conversation.conversation_id
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    extract = client.post(
        "/v1/candidates/extract",
        json={
            "workspace": "default",
            "conversation_id": conversation_id,
            "include_style": True,
            "include_psychometrics": True,
            "actor": _actor(settings),
        },
    )

    assert extract.status_code == 200
    domains = {item["domain"] for item in extract.json()["items"]}
    assert "style" in domains
    assert "psychometrics" in domains


def test_api_publish_rejects_invalid_candidate_status(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings, candidate_status="needs_review")
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/candidates/publish",
        json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)},
    )

    assert response.status_code == 422
    assert "Cannot publish candidate with status needs_review" in response.json()["detail"]


def test_api_publish_rejects_missing_canonical_key(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings)
    with get_connection(settings.db_path) as conn:
        conn.execute("UPDATE fact_candidates SET canonical_key = '', dedupe_key = '' WHERE id = ?", (candidate_id,))
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "without canonical_key" in response.json()["detail"]


def test_api_publish_rejects_missing_payload(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings)
    with get_connection(settings.db_path) as conn:
        conn.execute("UPDATE fact_candidates SET payload_json = '{}' WHERE id = ?", (candidate_id,))
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "without payload" in response.json()["detail"]


def test_api_publish_rejects_missing_evidence(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings)
    with get_connection(settings.db_path) as conn:
        conn.execute("UPDATE fact_candidates SET evidence_json = '[]' WHERE id = ?", (candidate_id,))
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "without evidence" in response.json()["detail"]


def test_api_publish_rejects_missing_segment_provenance(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings)
    with get_connection(settings.db_path) as conn:
        conn.execute(
            "UPDATE fact_candidates SET evidence_json = '[{\"quote\":\"Alice lives in Lisbon.\",\"message_ids\":[\"1\"],\"chunk_kind\":\"conversation\"}]' WHERE id = ?",
            (candidate_id,),
        )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "source-segment provenance" in response.json()["detail"]


def test_api_publish_rejects_low_confidence(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings, confidence=0.5)
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "confidence threshold" in response.json()["detail"]


def test_api_publish_rejects_unresolved_social_target(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(
        settings,
        domain="social_circle",
        category="friend",
        canonical_key="alice:social_circle:friend:bob",
        payload={"relation": "friend", "target_label": "Bob", "target_person_id": None},
        summary="Alice says Bob is their friend.",
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "unresolved hard conflict" in response.json()["detail"]


def test_api_publish_rejects_workspace_scope_mismatch(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings, workspace="default")
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post("/v1/candidates/publish", json={"workspace": "other-workspace", "candidate_id": candidate_id, "actor": _actor(settings)})

    assert response.status_code == 422
    assert "workspace scope" in response.json()["detail"]


def test_api_publish_rejects_workspace_scope_mismatch_for_published_candidate(monkeypatch, settings):
    candidate_id = _seed_publish_candidate(settings, workspace="default")
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    first = client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": candidate_id, "actor": _actor(settings)})
    assert first.status_code == 200

    second = client.post("/v1/candidates/publish", json={"workspace": "other-workspace", "candidate_id": candidate_id, "actor": _actor(settings)})
    assert second.status_code == 422
    assert "workspace scope" in second.json()["detail"]

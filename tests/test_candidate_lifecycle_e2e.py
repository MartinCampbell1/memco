from __future__ import annotations

import json

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.repositories.fact_repository import FactRepository
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.ingest_service import IngestService


def _actor():
    return {
        "actor_id": "dev-owner",
        "actor_type": "owner",
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": True,
    }


def _import_conversation(settings, tmp_path, name: str, messages: list[dict]) -> int:
    path = tmp_path / name
    path.write_text(json.dumps({"messages": messages}, ensure_ascii=False), encoding="utf-8")
    with get_connection(settings.db_path) as conn:
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=path,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
    return conversation.conversation_id


def test_biography_move_flow_extract_publish_retrieve_and_chat(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    conversation_id = _import_conversation(
        settings,
        tmp_path,
        "move.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    extract = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": conversation_id})
    biography = next(item for item in extract.json()["items"] if item["domain"] == "biography")
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": biography["id"]})

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor()},
    )
    assert retrieve.status_code == 200
    hits = retrieve.json()["hits"]
    assert len(hits) == 1
    assert hits[0]["payload"]["city"] == "Lisbon"
    assert hits[0]["evidence"][0]["source_segment_id"] is not None

    chat = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor()},
    )
    assert chat.status_code == 200
    assert chat.json()["refused"] is False
    assert "Lisbon" in chat.json()["answer"]


def test_biography_move_supersedes_previous_residence(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    first_conversation = _import_conversation(
        settings,
        tmp_path,
        "move-1.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T09:00:00Z", "text": "I live in Berlin."}],
    )
    second_conversation = _import_conversation(
        settings,
        tmp_path,
        "move-2.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T12:00:00Z", "text": "I moved to Lisbon."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    first_items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": first_conversation}).json()["items"]
    first_bio = next(item for item in first_items if item["domain"] == "biography")
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": first_bio["id"]})

    second_items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": second_conversation}).json()["items"]
    second_bio = next(item for item in second_items if item["domain"] == "biography")
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": second_bio["id"]})

    facts = client.post(
        "/v1/facts/list",
        json={"workspace": "default", "domain": "biography"},
    )
    assert facts.status_code == 200
    fact_items = facts.json()["items"]
    statuses = {item["summary"]: item["status"] for item in fact_items}
    assert statuses["Alice lives in Lisbon."] == "active"
    assert statuses["Alice lives in Berlin."] == "superseded"

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor()},
    )
    assert retrieve.status_code == 200
    assert len(retrieve.json()["hits"]) == 1
    assert retrieve.json()["hits"][0]["payload"]["city"] == "Lisbon"

    historical = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Where did Alice live before Lisbon?", "actor": _actor()},
    )
    assert historical.status_code == 200
    assert historical.json()["support_level"] == "full"
    assert historical.json()["hits"][0]["payload"]["city"] == "Berlin"
    assert historical.json()["hits"][0]["status"] == "superseded"


def test_preferences_reversal_and_person_isolation(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        fact_repo.upsert_person(
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
    first_conversation = _import_conversation(
        settings,
        tmp_path,
        "prefs1.json",
        [
            {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I like tea."},
            {"speaker": "Bob", "timestamp": "2026-04-21T10:01:00Z", "text": "I like coffee."},
        ],
    )
    second_conversation = _import_conversation(
        settings,
        tmp_path,
        "prefs2.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T11:00:00Z", "text": "I prefer coffee."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    first_items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": first_conversation}).json()["items"]
    alice_tea = next(item for item in first_items if item["person_id"] is not None and item["summary"].startswith("Alice"))
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": alice_tea["id"]})

    second_items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": second_conversation}).json()["items"]
    alice_coffee = next(item for item in second_items if item["domain"] == "preferences")
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": alice_coffee["id"]})

    alice_retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "What does Alice prefer?", "actor": _actor()},
    )
    bob_retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "bob", "query": "What does Bob prefer?", "actor": _actor()},
    )

    alice_values = [hit["payload"].get("value") for hit in alice_retrieve.json()["hits"]]
    assert "tea" in alice_values or "coffee" in alice_values
    assert all(hit["payload"].get("value") != "coffee" for hit in bob_retrieve.json()["hits"])


def test_work_and_experience_domains_flow(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    conversation_id = _import_conversation(
        settings,
        tmp_path,
        "work-exp.json",
        [
            {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I work as a software engineer."},
            {"speaker": "Alice", "timestamp": "2026-04-21T10:05:00Z", "text": "I attended PyCon."},
        ],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": conversation_id}).json()["items"]
    employment = next(item for item in items if item["domain"] == "work")
    experience = next(item for item in items if item["domain"] == "experiences")
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": employment["id"]})
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": experience["id"]})

    work_retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "What does Alice do for work?", "domain": "work", "actor": _actor()},
    )
    experiences_retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "What did Alice attend?", "domain": "experiences", "actor": _actor()},
    )

    assert work_retrieve.status_code == 200
    assert experiences_retrieve.status_code == 200
    assert any(hit["payload"].get("title") == "software engineer" for hit in work_retrieve.json()["hits"])
    assert any(hit["payload"].get("event") == "PyCon" for hit in experiences_retrieve.json()["hits"])


def test_social_circle_rejected_candidate_never_appears(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    conversation_id = _import_conversation(
        settings,
        tmp_path,
        "social.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "Bob is my friend."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": conversation_id}).json()["items"]
    social = next(item for item in items if item["domain"] == "social_circle")
    client.post("/v1/candidates/reject", json={"candidate_id": social["id"], "reason": "target unresolved"})

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Who is Alice friends with?", "actor": _actor()},
    )
    chat = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Who is Alice friends with?", "actor": _actor()},
    )

    assert retrieve.status_code == 200
    assert retrieve.json()["hits"] == []
    assert retrieve.json()["unsupported_premise_detected"] is True
    assert chat.status_code == 200
    assert chat.json()["refused"] is True


def test_retrieve_returns_fallback_hits_without_promoting_claim(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    conversation_id = _import_conversation(
        settings,
        tmp_path,
        "fallback.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I attended PyCon."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": conversation_id})

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Did Alice attend PyCon?", "actor": _actor()},
    )

    assert retrieve.status_code == 200
    payload = retrieve.json()
    assert payload["hits"] == []
    assert payload["unsupported_premise_detected"] is True
    assert len(payload["fallback_hits"]) >= 1
    assert "PyCon" in payload["fallback_hits"][0]["text"]


def test_duplicate_publish_merges_evidence(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    first = _import_conversation(
        settings,
        tmp_path,
        "dup-1.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I like tea."}],
    )
    second = _import_conversation(
        settings,
        tmp_path,
        "dup-2.json",
        [{"speaker": "Alice", "timestamp": "2026-04-21T11:00:00Z", "text": "I like tea."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    first_items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": first}).json()["items"]
    second_items = client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": second}).json()["items"]
    first_pref = next(item for item in first_items if item["domain"] == "preferences")
    second_pref = next(item for item in second_items if item["domain"] == "preferences")
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": first_pref["id"]})
    client.post("/v1/candidates/publish", json={"workspace": "default", "candidate_id": second_pref["id"]})

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "What does Alice like?", "actor": _actor()},
    )
    assert retrieve.status_code == 200
    hits = retrieve.json()["hits"]
    assert len(hits) == 1
    assert hits[0]["payload"]["value"] == "tea"
    assert len(hits[0]["evidence"]) == 2


def test_rejected_review_candidate_cannot_leak_to_retrieval(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
    conversation_id = _import_conversation(
        settings,
        tmp_path,
        "review-reject.json",
        [{"speaker": "Guest", "timestamp": "2026-04-21T10:00:00Z", "text": "Bob is my friend."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    client.post("/v1/candidates/extract", json={"workspace": "default", "conversation_id": conversation_id})
    queue_item = client.post("/v1/review/list", json={"workspace": "default", "status": "pending"}).json()["items"][0]
    resolved = client.post(
        "/v1/review/resolve",
        json={"queue_id": queue_item["id"], "decision": "rejected", "reason": "bad relation"},
    )
    assert resolved.status_code == 200

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "alice", "query": "Who is Alice friends with?", "actor": _actor()},
    )
    assert retrieve.status_code == 200
    assert retrieve.json()["hits"] == []


def test_speaker_resolution_reextracts_publishable_candidates(monkeypatch, settings, tmp_path):
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Guest User",
            slug="guest-user",
            person_type="human",
            aliases=["Guest User"],
        )
    conversation_id = _import_conversation(
        settings,
        tmp_path,
        "speaker-resolution.json",
        [{"speaker": "Guest", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."}],
    )
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    speakers = client.post(
        "/v1/conversations/speakers",
        json={"workspace": "default", "conversation_id": conversation_id},
    )
    assert speakers.status_code == 200
    assert speakers.json()["items"][0]["person_id"] is None

    resolved = client.post(
        "/v1/conversations/speakers/resolve",
        json={
            "workspace": "default",
            "conversation_id": conversation_id,
            "speaker_key": "guest",
            "person_slug": "guest-user",
        },
    )
    assert resolved.status_code == 200
    items = resolved.json()["candidates"]
    biography = next(item for item in items if item["domain"] == "biography")
    assert biography["person_id"] is not None
    assert biography["candidate_status"] == "validated_candidate"

    publish = client.post(
        "/v1/candidates/publish",
        json={"workspace": "default", "candidate_id": biography["id"]},
    )
    assert publish.status_code == 200

    retrieve = client.post(
        "/v1/retrieve",
        json={"workspace": "default", "person_slug": "guest-user", "query": "Where does Guest User live?", "actor": _actor()},
    )
    assert retrieve.status_code == 200
    assert retrieve.json()["hits"][0]["payload"]["city"] == "Lisbon"

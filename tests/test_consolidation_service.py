from __future__ import annotations

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService
from memco.services.retrieval_service import RetrievalService
from memco.models.retrieval import RetrievalRequest


def _seed_person_and_source(conn, *, parsed_text: str = "Alice memory note."):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    source_key = str(sum(ord(char) for char in parsed_text))
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
        source_path="var/raw/consolidation-note.md",
        source_type="note",
        origin_uri="/tmp/consolidation-note.md",
        title="consolidation-note",
        sha256=f"consolidation-note-{source_key}",
        parsed_text=parsed_text,
    )
    return person, source_id


def test_add_fact_persists_fact_and_evidence(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/note.md",
            source_type="note",
            origin_uri="/tmp/note.md",
            title="note",
            sha256="abc123",
            parsed_text="Alice likes tea.",
        )
        payload = MemoryFactInput(
            workspace="default",
            person_id=int(person["id"]),
            domain="preferences",
            category="food_drink",
            canonical_key="alice:preferences:drink.favorite:tea",
            payload={"value": "tea"},
            summary="Alice likes tea.",
            confidence=0.9,
            observed_at="2026-04-21T10:00:00Z",
            source_id=source_id,
            quote_text="Alice likes tea.",
        )
        fact = service.add_fact(conn, payload)

    assert fact["domain"] == "preferences"
    assert fact["payload"]["value"] == "tea"
    assert len(fact["evidence"]) == 1


def test_add_fact_merges_duplicate_evidence_and_preserves_locator(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/note-dup.md",
            source_type="note",
            origin_uri="/tmp/note-dup.md",
            title="note-dup",
            sha256="abc124",
            parsed_text="Alice likes tea.",
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text="Alice likes tea.")
        chunk_id = conn.execute(
            "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
            (source_id,),
        ).fetchone()["id"]
        payload = MemoryFactInput(
            workspace="default",
            person_id=int(person["id"]),
            domain="preferences",
            category="food_drink",
            canonical_key="alice:preferences:drink.favorite:tea",
            payload={"value": "tea"},
            summary="Alice likes tea.",
            confidence=0.9,
            observed_at="2026-04-21T10:00:00Z",
            source_id=source_id,
            quote_text="Alice likes tea.",
        )
        first = service.add_fact(conn, payload, locator={"message_ids": ["1"]}, source_chunk_id=int(chunk_id))
        second = service.add_fact(conn, payload, locator={"message_ids": ["2"]}, source_chunk_id=int(chunk_id))

    assert first["id"] == second["id"]
    assert len(second["evidence"]) == 2
    assert second["evidence"][0]["locator_json"]["message_ids"] == ["1"]
    assert second["evidence"][1]["locator_json"]["message_ids"] == ["2"]
    assert second["evidence"][0]["source_segment_id"] is not None
    assert second["evidence"][1]["source_segment_id"] is not None


def test_semantic_duplicate_merges_with_different_canonical_key_same_category(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/semantic-dup.md",
            source_type="note",
            origin_uri="/tmp/semantic-dup.md",
            title="semantic-dup",
            sha256="semantic-dup-sha",
            parsed_text="Alice likes tea.",
        )
        first = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea",
                payload={"value": "Tea", "polarity": "like", "reason": "warm"},
                summary="Alice likes tea.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice likes tea.",
            ),
        )
        second = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:black-tea",
                payload={"value": " tea ", "polarity": "like", "reason": "with breakfast"},
                summary="Alice still likes tea.",
                confidence=0.92,
                observed_at="2026-04-22T10:00:00Z",
                source_id=source_id,
                quote_text="Alice still likes tea.",
            ),
        )

    assert first["id"] == second["id"]
    assert len(second["evidence"]) == 2


def test_semantic_duplicate_detection_does_not_merge_unrelated_categories(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/category-guard.md",
            source_type="note",
            origin_uri="/tmp/category-guard.md",
            title="category-guard",
            sha256="category-guard-sha",
            parsed_text="Alice knows Python and uses Python.",
        )
        skill = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="skill",
                canonical_key="alice:work:python",
                payload={"skill": "Python"},
                summary="Alice knows Python.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice knows Python.",
            ),
        )
        tool = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="tool",
                canonical_key="alice:work:python",
                payload={"tool": "Python"},
                summary="Alice uses Python.",
                confidence=0.9,
                observed_at="2026-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Alice uses Python.",
            ),
        )

    assert skill["id"] != tool["id"]
    assert skill["category"] == "skill"
    assert tool["category"] == "tool"
    assert skill["status"] == "active"
    assert tool["status"] == "active"


def test_residence_value_conflict_supersedes_previous_current_fact(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/residence-conflict.md",
            source_type="note",
            origin_uri="/tmp/residence-conflict.md",
            title="residence-conflict",
            sha256="residence-conflict-sha",
            parsed_text="Alice lived in Berlin and later moved to Lisbon.",
        )
        berlin = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Alice lives in Berlin.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lived in Berlin.",
            ),
        )
        lisbon = service.add_fact(
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
                quote_text="Alice moved to Lisbon.",
            ),
        )
        berlin = fact_repo.get_fact(conn, fact_id=int(berlin["id"]))
        lisbon = fact_repo.get_fact(conn, fact_id=int(lisbon["id"]))

    assert berlin["status"] == "superseded"
    assert lisbon["status"] == "active"
    assert lisbon["supersedes_fact_id"] == berlin["id"]


def test_preference_polarity_conflict_supersedes_previous_preference(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/preference-conflict.md",
            source_type="note",
            origin_uri="/tmp/preference-conflict.md",
            title="preference-conflict",
            sha256="preference-conflict-sha",
            parsed_text="Alice liked tea and later disliked tea.",
        )
        like_fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea:like",
                payload={"value": "tea", "polarity": "like", "strength": "medium", "reason": "", "is_current": True},
                summary="Alice likes tea.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice liked tea.",
            ),
        )
        dislike_fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea:dislike",
                payload={"value": "tea", "polarity": "dislike", "strength": "medium", "reason": "", "is_current": True},
                summary="Alice dislikes tea.",
                confidence=0.92,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice later disliked tea.",
            ),
        )
        like_fact = fact_repo.get_fact(conn, fact_id=int(like_fact["id"]))
        dislike_fact = fact_repo.get_fact(conn, fact_id=int(dislike_fact["id"]))

    assert like_fact["status"] == "superseded"
    assert dislike_fact["status"] == "active"
    assert dislike_fact["supersedes_fact_id"] == like_fact["id"]


def test_temporal_conflict_inserts_historical_fact_without_replacing_current(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()
    retrieval = RetrievalService()

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
            source_path="var/raw/temporal-conflict.md",
            source_type="note",
            origin_uri="/tmp/temporal-conflict.md",
            title="temporal-conflict",
            sha256="temporal-conflict-sha",
            parsed_text="Alice lives in Lisbon now and previously lived in Berlin.",
        )
        current_fact = service.add_fact(
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
                quote_text="Alice lives in Lisbon now.",
            ),
        )
        historical_fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Alice lived in Berlin.",
                confidence=0.88,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice previously lived in Berlin.",
            ),
        )
        current = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?"),
        )
        history = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where did Alice live before Lisbon?", temporal_mode="history"),
        )
        history_auto = retrieval.retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where did Alice use to live?"),
        )

    assert current_fact["status"] == "active"
    assert historical_fact["status"] == "superseded"
    assert historical_fact["superseded_by_fact_id"] == current_fact["id"]
    assert current.hits[0].payload["city"] == "Lisbon"
    assert any(hit.payload["city"] == "Berlin" for hit in history.hits)
    assert history_auto.planner.temporal_mode == "history"
    assert any(hit.payload["city"] == "Berlin" for hit in history_auto.hits)


def test_event_fact_persists_event_at_without_validity_window(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    service = ConsolidationService()

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
            source_path="var/raw/event-time.md",
            source_type="note",
            origin_uri="/tmp/event-time.md",
            title="event-time",
            sha256="event-time-sha",
            parsed_text="Alice attended PyCon in 2025.",
        )
        fact = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon",
                payload={"event": "PyCon"},
                summary="Alice attended PyCon.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                event_at="2025",
                source_id=source_id,
                quote_text="Alice attended PyCon in 2025.",
            ),
        )

    assert fact["observed_at"] == "2026-04-21T10:00:00Z"
    assert fact["event_at"] == "2025"
    assert fact["valid_from"] == ""
    assert fact["valid_to"] == ""


def test_preference_current_state_scope_keeps_unrelated_preferences_active(settings):
    service = ConsolidationService()
    fact_repo = FactRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn, parsed_text="Alice likes tea and coffee.")
        tea = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea:like",
                payload={"value": "tea", "polarity": "like", "is_current": True},
                summary="Alice likes tea.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice likes tea.",
            ),
        )
        coffee = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:coffee:like",
                payload={"value": "coffee", "polarity": "like", "is_current": True},
                summary="Alice likes coffee.",
                confidence=0.9,
                observed_at="2026-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Alice likes coffee.",
            ),
        )
        tea = fact_repo.get_fact(conn, fact_id=int(tea["id"]))
        coffee = fact_repo.get_fact(conn, fact_id=int(coffee["id"]))

    assert tea["status"] == "active"
    assert coffee["status"] == "active"


def test_social_relationship_update_supersedes_same_target_only(settings):
    service = ConsolidationService()
    fact_repo = FactRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn, parsed_text="Alice knows Bob and Charlie.")
        bob_friend = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="social_circle",
                category="friend",
                canonical_key="alice:social_circle:friend:bob",
                payload={"relation": "friend", "target_label": "Bob", "target_person_id": 101, "is_current": True},
                summary="Bob is Alice's friend.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob is Alice's friend.",
            ),
        )
        charlie_friend = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="social_circle",
                category="friend",
                canonical_key="alice:social_circle:friend:charlie",
                payload={"relation": "friend", "target_label": "Charlie", "target_person_id": 102, "is_current": True},
                summary="Charlie is Alice's friend.",
                confidence=0.9,
                observed_at="2025-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Charlie is Alice's friend.",
            ),
        )
        bob_partner = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="social_circle",
                category="partner",
                canonical_key="alice:social_circle:partner:bob",
                payload={"relation": "partner", "target_label": "Bob", "target_person_id": 101, "is_current": True},
                summary="Bob is Alice's partner.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob is Alice's partner.",
            ),
        )
        bob_friend = fact_repo.get_fact(conn, fact_id=int(bob_friend["id"]))
        charlie_friend = fact_repo.get_fact(conn, fact_id=int(charlie_friend["id"]))
        bob_partner = fact_repo.get_fact(conn, fact_id=int(bob_partner["id"]))

    assert bob_friend["status"] == "superseded"
    assert bob_friend["superseded_by_fact_id"] == bob_partner["id"]
    assert bob_partner["status"] == "active"
    assert bob_partner["supersedes_fact_id"] == bob_friend["id"]
    assert charlie_friend["status"] == "active"


def test_experience_event_merges_by_event_date_location(settings):
    service = ConsolidationService()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn, parsed_text="Alice attended PyCon in Lisbon.")
        first = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon-lisbon",
                payload={"event": "PyCon", "location": "Lisbon"},
                summary="Alice attended PyCon in Lisbon.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                event_at="2025-05",
                source_id=source_id,
                quote_text="Alice attended PyCon in Lisbon.",
            ),
        )
        second = service.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon-2025-lisbon",
                payload={"event": "pycon", "location": " lisbon "},
                summary="Alice went to PyCon 2025 in Lisbon.",
                confidence=0.92,
                observed_at="2026-04-22T10:00:00Z",
                event_at="2025-05",
                source_id=source_id,
                quote_text="Alice went to PyCon 2025 in Lisbon.",
            ),
        )

    assert second["id"] == first["id"]
    assert len(second["evidence"]) == 2


def test_consolidation_batch_returns_per_run_report(settings):
    service = ConsolidationService()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn, parsed_text="Alice moved from Berlin to Lisbon.")
        result = service.add_facts(
            conn,
            [
                MemoryFactInput(
                    workspace="default",
                    person_id=int(person["id"]),
                    domain="biography",
                    category="residence",
                    canonical_key="alice:biography:residence:berlin",
                    payload={"city": "Berlin"},
                    summary="Alice lives in Berlin.",
                    confidence=0.9,
                    observed_at="2025-04-21T10:00:00Z",
                    source_id=source_id,
                    quote_text="Alice lives in Berlin.",
                ),
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
                    quote_text="Alice moved to Lisbon.",
                ),
            ],
        )

    report = result["report"]
    assert report == service.last_report
    assert report["run_id"]
    assert report["total"] == 2
    assert report["inserted"] == 2
    assert report["inserted_active"] == 1
    assert report["superseded"] == 1
    assert report["superseded_existing"] == 1
    assert report["conflicts"][0]["supersedes_fact_id"] == result["facts"][0]["id"]
    assert report["by_domain"]["biography"]["total"] == 2
    assert result["facts"][0]["status"] == "superseded"
    assert result["facts"][0]["superseded_by_fact_id"] == result["facts"][1]["id"]
    assert [item["status"] for item in report["operations"]] == ["active", "active"]
    assert report["operations"][0]["final_status"] == "superseded"
    assert report["operations"][1]["supersedes_fact_id"] == result["facts"][0]["id"]

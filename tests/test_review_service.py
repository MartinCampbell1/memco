from __future__ import annotations

from memco.db import get_connection
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.review_repository import ReviewRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.review_service import ReviewService


def _seed_review_candidate(conn):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    candidate_repo = CandidateRepository()
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
        source_path="var/raw/review-source.md",
        source_type="note",
        origin_uri="/tmp/review-source.md",
        title="review-source",
        sha256="review-source-sha",
        parsed_text="Alice says Bob is my friend.",
    )
    candidate = candidate_repo.add_candidate(
        conn,
        workspace_slug="default",
        person_id=int(person["id"]),
        source_id=source_id,
        conversation_id=None,
        chunk_kind="conversation",
        chunk_id=1,
        domain="social_circle",
        category="friend",
        subcategory="",
        canonical_key="alice:social_circle:friend:bob",
        payload={"relation": "friend", "target_label": "Bob", "target_person_id": None},
        summary="Alice says Bob is their friend.",
        confidence=0.55,
        reason="relation_target_unresolved",
    )
    candidate = candidate_repo.mark_candidate_status(
        conn,
        candidate_id=int(candidate["id"]),
        candidate_status="needs_review",
        reason="relation_target_unresolved",
    )
    return person, candidate


def test_enqueue_review_queue_serializes_candidate_snapshot_and_reason(settings):
    repository = ReviewRepository()

    with get_connection(settings.db_path) as conn:
        person, candidate = _seed_review_candidate(conn)
        queue_id = repository.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )
        row = repository.resolve(conn, queue_id=queue_id, decision="pending")

    assert row["candidate_id"] == int(candidate["id"])
    assert row["status"] == "pending"
    assert row["reason"] == "relation_target_unresolved"
    assert row["candidate"]["canonical_key"] == "alice:social_circle:friend:bob"


def test_resolve_review_queue_updates_status_and_candidate_state(settings):
    repository = ReviewRepository()
    service = ReviewService()

    with get_connection(settings.db_path) as conn:
        person, candidate = _seed_review_candidate(conn)
        queue_id = repository.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )
        result = service.resolve(
            conn,
            queue_id=queue_id,
            decision="approved",
            reason="reviewed manually",
        )
        refreshed = CandidateRepository().get_candidate(conn, candidate_id=int(candidate["id"]))

    assert result["status"] == "approved"
    assert result["resolved_at"] != ""
    assert result["reason"] == "reviewed manually"
    assert result["candidate"]["id"] == int(candidate["id"])
    assert refreshed["candidate_status"] == "validated_candidate"


def test_resolve_review_queue_with_person_assignment(settings):
    repository = ReviewRepository()
    service = ReviewService()

    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        bob = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        person, candidate = _seed_review_candidate(conn)
        queue_id = repository.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )
        result = service.resolve_with_person(
            conn,
            queue_id=queue_id,
            decision="approved",
            reason="resolved target manually",
            candidate_person_id=int(person["id"]),
        )
        refreshed = CandidateRepository().get_candidate(conn, candidate_id=int(candidate["id"]))

    assert result["status"] == "approved"
    assert refreshed["person_id"] == int(person["id"])
    assert refreshed["candidate_status"] == "validated_candidate"


def test_resolve_review_queue_with_target_person_assignment(settings):
    repository = ReviewRepository()
    service = ReviewService()

    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        bob = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        person, candidate = _seed_review_candidate(conn)
        queue_id = repository.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )
        result = service.resolve_with_person(
            conn,
            queue_id=queue_id,
            decision="approved",
            reason="resolved target manually",
            candidate_person_id=int(person["id"]),
            candidate_target_person_id=int(bob["id"]),
        )
        refreshed = CandidateRepository().get_candidate(conn, candidate_id=int(candidate["id"]))

    assert result["status"] == "approved"
    assert refreshed["candidate_status"] == "validated_candidate"
    assert refreshed["payload"]["target_person_id"] == int(bob["id"])


def test_rejected_review_does_not_mutate_candidate_person_or_target(settings):
    repository = ReviewRepository()
    service = ReviewService()

    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        bob = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        person, candidate = _seed_review_candidate(conn)
        queue_id = repository.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )
        result = service.resolve_with_person(
            conn,
            queue_id=queue_id,
            decision="rejected",
            reason="reject without mutation",
            candidate_person_id=int(person["id"]),
            candidate_target_person_id=int(bob["id"]),
        )
        refreshed = CandidateRepository().get_candidate(conn, candidate_id=int(candidate["id"]))

    assert result["status"] == "rejected"
    assert refreshed["candidate_status"] == "rejected"
    assert refreshed["person_id"] == int(person["id"])
    assert refreshed["payload"]["target_person_id"] is None


def test_list_items_for_candidates_does_not_drop_older_matching_review_items(settings):
    repository = ReviewRepository()

    with get_connection(settings.db_path) as conn:
        person, candidate = _seed_review_candidate(conn)
        queue_id = repository.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )
        for index in range(101):
            repository.enqueue(
                conn,
                workspace_slug="default",
                person_id=None,
                candidate={"index": index},
                reason="other",
                candidate_id=None,
            )

        items = repository.list_items_for_candidates(
            conn,
            workspace_slug="default",
            candidate_ids=[int(candidate["id"])],
            status="pending",
        )

    assert len(items) == 1
    assert items[0]["id"] == queue_id

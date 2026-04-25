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


def _psychometrics_payload() -> dict:
    evidence_quotes = ["I often seek new ideas.", "I enjoy exploring unfamiliar topics."]
    counterevidence_quotes: list[str] = []
    return {
        "framework": "big_five",
        "trait": "openness",
        "score": 0.72,
        "score_scale": "0_to_1",
        "direction": "high",
        "confidence": 0.72,
        "extracted_signal": {
            "signal_kind": "self_description",
            "explicit_self_description": True,
            "signal_confidence": 0.72,
            "evidence_count": len(evidence_quotes),
            "counterevidence_count": len(counterevidence_quotes),
            "evidence_quotes": evidence_quotes,
            "counterevidence_quotes": counterevidence_quotes,
        },
        "scored_profile": {
            "score": 0.72,
            "score_scale": "0_to_1",
            "direction": "high",
            "confidence": 0.72,
            "framework_threshold": 0.7,
            "conservative_update": True,
            "use_in_generation": True,
        },
        "evidence_quotes": evidence_quotes,
        "counterevidence_quotes": counterevidence_quotes,
        "conservative_update": True,
        "use_in_generation": True,
        "safety_notes": "Non-diagnostic review-only inference.",
    }


def test_enqueue_review_queue_serializes_candidate_snapshot_and_reason(settings):
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
        row = service.list_items(conn, workspace_slug="default", status="pending")[0]

    assert row["candidate_id"] == int(candidate["id"])
    assert row["status"] == "pending"
    assert row["reason"] == "relation_target_unresolved"
    assert row["candidate"]["canonical_key"] == "alice:social_circle:friend:bob"
    assert row["candidate_reason_codes"] == ["relation_target_unresolved"]
    assert row["candidate_domain"] == "social_circle"
    assert row["candidate_summary"] == "Alice says Bob is their friend."
    assert row["next_action_hint"] == "review-resolve approved|rejected"


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


def test_review_resolution_reason_is_enriched_for_operator_use(settings):
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
        result = service.resolve_with_person(
            conn,
            queue_id=queue_id,
            decision="approved",
            reason="resolved target manually",
            candidate_person_id=int(person["id"]),
        )

    assert "resolution_reason" in result
    assert result["resolution_reason"] == "resolved target manually"
    assert "decision_summary" in result
    assert "approved" in result["decision_summary"]
    assert result["candidate_reason"] == "resolved target manually"
    assert result["candidate_reason_codes"] == ["resolved target manually"]


def test_review_service_rejects_invalid_decision(settings):
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
        try:
            service.resolve_with_person(
                conn,
                queue_id=queue_id,
                decision="maybe",
                reason="invalid state",
            )
        except ValueError as exc:
            assert "decision must be one of" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected invalid review decision to be rejected")


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


def test_review_dashboard_surfaces_cards_flags_evidence_and_consolidation_preview(settings):
    service = ReviewService()

    with get_connection(settings.db_path) as conn:
        person, social_candidate = _seed_review_candidate(conn)
        fact_repo = FactRepository()
        source_repo = SourceRepository()
        candidate_repo = CandidateRepository()
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/review-dashboard.md",
            source_type="note",
            origin_uri="/tmp/review-dashboard.md",
            title="review-dashboard",
            sha256="review-dashboard-sha",
            parsed_text="Alice lives in Lisbon and may be open to new ideas.",
        )
        social_candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(social_candidate["id"]),
            evidence=[
                {
                    "quote": "Bob is my friend.",
                    "message_ids": ["1"],
                    "source_segment_ids": [10],
                    "chunk_kind": "conversation",
                }
            ],
        )
        ReviewRepository().enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=social_candidate,
            reason="relation_target_unresolved",
            candidate_id=int(social_candidate["id"]),
        )
        fact_repo.add_fact(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:lisbon",
            payload={"city": "Lisbon"},
            summary="Alice lives in Lisbon.",
            source_kind="manual",
            confidence=0.9,
            observed_at="2026-04-21T10:00:00Z",
            valid_from="",
            valid_to="",
            event_at="",
            source_id=source_id,
            quote_text="Alice lives in Lisbon.",
        )
        residence_candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="source",
            chunk_id=None,
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:porto",
            payload={"city": "Porto"},
            summary="Alice lives in Porto.",
            confidence=0.93,
            reason="possible_current_update",
            extracted_at="2026-04-22T10:00:00Z",
        )
        family_candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="source",
            chunk_id=None,
            domain="biography",
            category="family",
            subcategory="",
            canonical_key="alice:biography:family:sister:maria",
            payload={"relation": "sister", "name": "Maria"},
            summary="Alice has a sister named Maria.",
            confidence=0.58,
            reason="sensitive_family_low_confidence",
        )
        family_candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(family_candidate["id"]),
            candidate_status="needs_review",
            reason="sensitive_family_low_confidence",
        )
        ReviewRepository().enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=family_candidate,
            reason="sensitive_family_low_confidence",
            candidate_id=int(family_candidate["id"]),
        )
        psychometrics_candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="source",
            chunk_id=None,
            domain="psychometrics",
            category="trait",
            subcategory="",
            canonical_key="alice:psychometrics:big_five:openness",
            payload=_psychometrics_payload(),
            summary="Alice may show openness.",
            confidence=0.72,
            reason="psychometrics_inference",
        )
        psychometrics_candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(psychometrics_candidate["id"]),
            candidate_status="needs_review",
            reason="psychometrics_inference",
        )
        dashboard = service.dashboard(
            conn,
            workspace_slug="default",
            status="pending",
            person_id=int(person["id"]),
        )
        biography_dashboard = service.dashboard(
            conn,
            workspace_slug="default",
            status="pending",
            person_id=int(person["id"]),
            domain="biography",
        )
        social_dashboard = service.dashboard(
            conn,
            workspace_slug="default",
            status="pending",
            person_id=int(person["id"]),
            domain="social_circle",
        )

    cards = {card["candidate_id"]: card for card in dashboard["candidate_cards"]}
    assert dashboard["summary"]["review_item_count"] == 2
    assert cards[int(social_candidate["id"])]["evidence_preview"][0]["quote"] == "Bob is my friend."
    assert "sensitive" in cards[int(family_candidate["id"])]["flags"]
    assert "low_confidence" in cards[int(family_candidate["id"])]["flags"]
    assert "psychometrics_inference" in cards[int(psychometrics_candidate["id"])]["flags"]
    assert cards[int(residence_candidate["id"])]["consolidation_preview"]["action"] == "supersede_existing"
    assert dashboard["summary"]["sensitive_count"] == 2
    assert dashboard["summary"]["psychometrics_inference_count"] == 1
    assert dashboard["summary"]["proposed_supersede_count"] == 1

    biography_cards = {card["candidate_id"]: card for card in biography_dashboard["candidate_cards"]}
    assert biography_dashboard["filters"]["domain"] == "biography"
    assert biography_dashboard["summary"]["review_item_count"] == 1
    assert set(biography_cards) == {int(residence_candidate["id"]), int(family_candidate["id"])}
    assert biography_dashboard["review_items"][0]["candidate_id"] == int(family_candidate["id"])

    social_cards = {card["candidate_id"]: card for card in social_dashboard["candidate_cards"]}
    assert social_dashboard["filters"]["domain"] == "social_circle"
    assert social_dashboard["summary"]["review_item_count"] == 1
    assert set(social_cards) == {int(social_candidate["id"])}
    assert social_dashboard["review_items"][0]["candidate_id"] == int(social_candidate["id"])

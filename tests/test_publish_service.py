from __future__ import annotations

import pytest

from memco.db import get_connection
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.publish_service import PublishService
from memco.services.retrieval_service import RetrievalService
from memco.models.retrieval import RetrievalRequest


def _seed_candidate(
    conn,
    *,
    person_id=None,
    candidate_status="validated_candidate",
    domain="biography",
    category="residence",
    subcategory="",
    canonical_key="alice:biography:residence:lisbon",
    payload=None,
    summary="Alice lives in Lisbon.",
    parsed_text="Alice lives in Lisbon.",
):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    candidate_repo = CandidateRepository()
    if person_id is None:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        person_id = int(person["id"])
    source_id = source_repo.record_source(
        conn,
        workspace_slug="default",
        source_path="var/raw/publish-source.md",
        source_type="note",
        origin_uri="/tmp/publish-source.md",
        title="publish-source",
        sha256="publish-source-sha",
        parsed_text=parsed_text,
    )
    source_repo.replace_chunks(conn, source_id=source_id, parsed_text=parsed_text)
    chunk_id = conn.execute(
        "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
        (source_id,),
    ).fetchone()["id"]
    source_segment_id = source_repo.get_segment_by_chunk_id(conn, chunk_id=int(chunk_id))["id"]
    candidate = candidate_repo.add_candidate(
        conn,
        workspace_slug="default",
        person_id=person_id,
        source_id=source_id,
        conversation_id=None,
        chunk_kind="conversation",
        chunk_id=int(chunk_id),
        domain=domain,
        category=category,
        subcategory=subcategory,
        canonical_key=canonical_key,
        payload=payload or {"city": "Lisbon"},
        summary=summary,
        confidence=0.91,
    )
    candidate = candidate_repo.update_candidate_evidence(
        conn,
        candidate_id=int(candidate["id"]),
        evidence=[
            {
                "quote": parsed_text,
                "message_ids": ["8"],
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
    return candidate


def test_publish_candidate_creates_active_fact_with_evidence_and_marks_candidate_published(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        result = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )

    assert result["candidate"]["candidate_status"] == "published"
    assert result["candidate"]["publish_target_fact_id"] == result["fact"]["id"]
    assert result["fact"]["person_id"] == candidate["person_id"]
    assert result["fact"]["domain"] == "biography"
    assert result["fact"]["category"] == "residence"
    assert result["fact"]["canonical_key"] == "alice:biography:residence:lisbon"
    assert result["fact"]["payload"]["city"] == "Lisbon"
    assert len(result["fact"]["evidence"]) == 1
    assert result["fact"]["evidence"][0]["quote_text"] == "Alice lives in Lisbon."
    assert result["fact"]["evidence"][0]["locator_json"]["message_ids"] == ["8"]
    assert result["fact"]["evidence"][0]["source_segment_id"] is not None


def test_publish_pdf_candidate_preserves_page_locator(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    candidate_repo = CandidateRepository()
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
            source_path="var/raw/pdf/alice.pdf",
            source_type="pdf",
            origin_uri="/tmp/alice.pdf",
            title="alice",
            sha256="pdf-sha",
            parsed_text="## Page 2\n\nAlice lives in Lisbon.",
        )
        source_repo.replace_chunks(
            conn,
            source_id=source_id,
            parsed_text="## Page 2\n\nAlice lives in Lisbon.",
            segments=[
                {
                    "segment_type": "pdf_page",
                    "segment_index": 1,
                    "section_title": "Page 2",
                    "text": "## Page 2\n\nAlice lives in Lisbon.",
                    "locator": {"page_number": 2, "page_label": "Page 2", "section_title": "Page 2"},
                }
            ],
        )
        chunk = conn.execute("SELECT id FROM source_chunks WHERE source_id = ?", (source_id,)).fetchone()
        segment = source_repo.get_segment_by_chunk_id(conn, chunk_id=int(chunk["id"]))
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="source",
            chunk_id=int(chunk["id"]),
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:lisbon",
            payload={"city": "Lisbon"},
            summary="Alice lives in Lisbon.",
            confidence=0.91,
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=[
                {
                    "quote": "Alice lives in Lisbon.",
                    "message_ids": [],
                    "source_segment_ids": [int(segment["id"])],
                    "chunk_kind": "source",
                    "source_type": "pdf",
                }
            ],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="validated_candidate",
        )
        result = PublishService().publish_candidate(conn, workspace_slug="default", candidate_id=int(candidate["id"]))
        retrieved = RetrievalService().retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Where does Alice live?",
            ),
        )

    evidence = result["fact"]["evidence"][0]
    assert evidence["quote_text"] == "Alice lives in Lisbon."
    assert evidence["source_segment_id"] == int(segment["id"])
    assert evidence["locator_json"]["source_segment_type"] == "pdf_page"
    assert evidence["locator_json"]["source_segment_locator"]["page_number"] == 2
    retrieved_evidence = retrieved.hits[0].evidence[0]
    assert retrieved_evidence["quote_text"] == "Alice lives in Lisbon."
    assert retrieved_evidence["source_segment_id"] == int(segment["id"])
    assert retrieved_evidence["locator_json"]["source_segment_locator"]["page_label"] == "Page 2"


def test_publish_candidate_promotes_extracted_valid_from(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn, payload={"city": "Lisbon", "valid_from": "2024"})
        result = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )

    assert result["fact"]["payload"]["city"] == "Lisbon"
    assert result["fact"]["valid_from"] == "2024"


def test_publish_family_candidate_creates_social_relationship_mirror(settings):
    service = PublishService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(
            conn,
            domain="biography",
            category="family",
            subcategory="sister",
            canonical_key="alice:biography:family:sister:maria",
            payload={"relation": "sister", "name": "Maria"},
            summary="Alice's sister is Maria.",
            parsed_text="Alice's sister is Maria.",
        )
        result = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )
        mirrored = result["mirrored_fact"]
        retrieved = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Who is Alice's sister?",
            ),
        )

    assert result["fact"]["domain"] == "biography"
    assert result["fact"]["category"] == "family"
    assert mirrored["domain"] == "social_circle"
    assert mirrored["category"] == "sister"
    assert mirrored["canonical_key"] == "alice:social_circle:sister:maria"
    assert mirrored["payload"]["target_label"] == "Maria"
    assert mirrored["payload"]["mirrored_from_fact_id"] == result["fact"]["id"]
    assert mirrored["evidence"][0]["locator_json"]["mirror_kind"] == "biography_family_to_social_circle"
    assert retrieved.support_level == "supported"
    assert len(retrieved.hits) == 1
    assert retrieved.hits[0].domain == "biography"
    assert retrieved.hits[0].category == "family"
    assert retrieved.hits[0].payload["name"] == "Maria"


def test_publish_candidate_is_idempotent_for_already_published_candidate(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        first = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )
        second = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )
        fact_count = conn.execute("SELECT COUNT(*) AS count FROM memory_facts").fetchone()["count"]

    assert first["fact"]["id"] == second["fact"]["id"]
    assert first["candidate"]["publish_target_fact_id"] == second["candidate"]["publish_target_fact_id"]
    assert fact_count == 1


def test_publish_candidate_rejects_workspace_scope_mismatch_after_publish(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )
        with pytest.raises(ValueError, match="workspace scope"):
            service.publish_candidate(
                conn,
                workspace_slug="other-workspace",
                candidate_id=int(candidate["id"]),
            )


def test_publish_candidate_rejects_unresolved_candidate(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn, person_id=None, candidate_status="needs_review")
        unresolved = candidate
        unresolved = {**unresolved, "person_id": None}
        conn.execute(
            "UPDATE fact_candidates SET person_id = NULL WHERE id = ?",
            (int(candidate["id"]),),
        )
        with pytest.raises(ValueError, match="Cannot publish candidate with status needs_review"):
            service.publish_candidate(
                conn,
                workspace_slug="default",
                candidate_id=int(candidate["id"]),
            )
        refreshed = CandidateRepository().get_candidate(conn, candidate_id=int(candidate["id"]))

    assert unresolved["candidate_status"] == "needs_review"
    assert refreshed["candidate_status"] == "needs_review"


def test_publish_candidate_rejects_missing_evidence(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        conn.execute("UPDATE fact_candidates SET evidence_json = '[]' WHERE id = ?", (int(candidate["id"]),))
        with pytest.raises(ValueError, match="without evidence"):
            service.publish_candidate(
                conn,
                workspace_slug="default",
                candidate_id=int(candidate["id"]),
            )


def test_publish_candidate_rejects_missing_segment_provenance(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        conn.execute(
            "UPDATE fact_candidates SET evidence_json = '[{\"quote\":\"Alice lives in Lisbon.\",\"message_ids\":[\"8\"],\"chunk_kind\":\"conversation\"}]' WHERE id = ?",
            (int(candidate["id"]),),
        )
        with pytest.raises(ValueError, match="source-segment provenance"):
            service.publish_candidate(
                conn,
                workspace_slug="default",
                candidate_id=int(candidate["id"]),
            )


def test_publish_candidate_rejects_low_confidence(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        conn.execute("UPDATE fact_candidates SET confidence = 0.5 WHERE id = ?", (int(candidate["id"]),))
        with pytest.raises(ValueError, match="confidence threshold"):
            service.publish_candidate(
                conn,
                workspace_slug="default",
                candidate_id=int(candidate["id"]),
            )


def test_publish_candidate_rejects_workspace_scope_mismatch(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        with pytest.raises(ValueError, match="workspace scope"):
            service.publish_candidate(
                conn,
                workspace_slug="other-workspace",
                candidate_id=int(candidate["id"]),
            )


def test_publish_candidate_auto_creates_unresolved_social_target(settings):
    service = PublishService()
    candidate_repo = CandidateRepository()
    fact_repo = FactRepository()
    source_repo = SourceRepository()

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
            source_path="var/raw/social-source.md",
            source_type="note",
            origin_uri="/tmp/social-source.md",
            title="social-source",
            sha256="social-source-sha",
            parsed_text="Bob is my friend.",
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text="Bob is my friend.")
        chunk_id = conn.execute(
            "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
            (source_id,),
        ).fetchone()["id"]
        source_segment_id = source_repo.get_segment_by_chunk_id(conn, chunk_id=int(chunk_id))["id"]
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=int(chunk_id),
            domain="social_circle",
            category="friend",
            subcategory="",
            canonical_key="alice:social_circle:friend:bob",
            payload={"relation": "friend", "target_label": "Bob", "target_person_id": None},
            summary="Alice says Bob is their friend.",
            confidence=0.9,
        )
        candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=[
                {
                    "quote": "Bob is my friend.",
                    "message_ids": ["1"],
                    "source_segment_ids": [int(source_segment_id)],
                    "chunk_kind": "conversation",
                }
            ],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="validated_candidate",
        )
        result = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )
        refreshed = candidate_repo.get_candidate(conn, candidate_id=int(candidate["id"]))
        bob = conn.execute(
            "SELECT * FROM persons WHERE slug = ?",
            ("bob",),
        ).fetchone()

    assert bob is not None
    assert result["fact"]["domain"] == "social_circle"
    assert result["fact"]["payload"]["target_person_id"] == int(bob["id"])
    assert refreshed["payload"]["target_person_id"] == int(bob["id"])


def test_publish_candidate_auto_creates_unresolved_social_relationship_event_target(settings):
    service = PublishService()
    candidate_repo = CandidateRepository()
    fact_repo = FactRepository()
    source_repo = SourceRepository()

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
            source_path="var/raw/social-event-source.md",
            source_type="note",
            origin_uri="/tmp/social-event-source.md",
            title="social-event-source",
            sha256="social-event-source-sha",
            parsed_text="I met Bob at work.",
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text="I met Bob at work.")
        chunk_id = conn.execute(
            "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
            (source_id,),
        ).fetchone()["id"]
        source_segment_id = source_repo.get_segment_by_chunk_id(conn, chunk_id=int(chunk_id))["id"]
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=int(chunk_id),
            domain="social_circle",
            category="relationship_event",
            subcategory="met",
            canonical_key="alice:social_circle:relationship_event:bob:met",
            payload={"target_label": "Bob", "target_person_id": None, "event": "met", "context": "work"},
            summary="Alice met Bob.",
            confidence=0.8,
        )
        candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=[
                {
                    "quote": "I met Bob at work.",
                    "message_ids": ["1"],
                    "source_segment_ids": [int(source_segment_id)],
                    "chunk_kind": "conversation",
                }
            ],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="validated_candidate",
        )
        result = service.publish_candidate(
            conn,
            workspace_slug="default",
            candidate_id=int(candidate["id"]),
        )
        refreshed = candidate_repo.get_candidate(conn, candidate_id=int(candidate["id"]))
        bob = conn.execute(
            "SELECT * FROM persons WHERE slug = ?",
            ("bob",),
        ).fetchone()

    assert bob is not None
    assert result["fact"]["category"] == "relationship_event"
    assert result["fact"]["payload"]["target_person_id"] == int(bob["id"])
    assert refreshed["payload"]["target_person_id"] == int(bob["id"])


def test_reject_candidate_marks_status_reason_and_does_not_create_fact(settings):
    service = PublishService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        rejected = service.reject_candidate(
            conn,
            candidate_id=int(candidate["id"]),
            reason="not enough evidence",
        )
        fact_count = conn.execute("SELECT COUNT(*) AS count FROM memory_facts").fetchone()["count"]

    assert rejected["candidate_status"] == "rejected"
    assert rejected["reason"] == "not enough evidence"
    assert rejected["published_at"] == ""
    assert fact_count == 0


def test_retrieval_excludes_rejected_candidates(settings):
    publish_service = PublishService()
    retrieval_service = RetrievalService()

    with get_connection(settings.db_path) as conn:
        candidate = _seed_candidate(conn)
        publish_service.reject_candidate(
            conn,
            candidate_id=int(candidate["id"]),
            reason="rejected",
        )
        result = retrieval_service.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Where does Alice live?",
            ),
        )

    assert result.unsupported_premise_detected is True
    assert result.hits == []

from __future__ import annotations

import pytest

from memco.db import get_connection
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository


def _seed_person_and_source(conn):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
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
        source_path="var/raw/candidate-source.md",
        source_type="note",
        origin_uri="/tmp/candidate-source.md",
        title="candidate-source",
        sha256="candidate-source-sha",
        parsed_text="Alice moved to Lisbon.",
    )
    return person, source_id


def test_add_candidate_persists_supported_p0a_domain_and_payload(settings):
    repository = CandidateRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn)
        candidate = repository.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=11,
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:lisbon",
            payload={"city": "Lisbon"},
            summary="Alice lives in Lisbon.",
            confidence=0.9,
        )

    assert candidate["candidate_status"] == "extracted_candidate"
    assert candidate["domain"] == "biography"
    assert candidate["payload"] == {"city": "Lisbon"}
    assert candidate["dedupe_key"] == "alice:biography:residence:lisbon"
    assert candidate["published_at"] == ""
    assert candidate["person_id"] == int(person["id"])
    assert candidate["source_id"] == source_id
    assert candidate["chunk_id"] == 11


def test_add_candidate_rejects_unknown_domain(settings):
    repository = CandidateRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn)
        with pytest.raises(ValueError, match="Unsupported candidate domain"):
            repository.add_candidate(
                conn,
                workspace_slug="default",
                person_id=int(person["id"]),
                source_id=source_id,
                conversation_id=None,
                chunk_kind="conversation",
                chunk_id=None,
                domain="finance",
                category="trait",
                subcategory="",
                canonical_key="alice:finance:trait:budget",
                payload={"trait": "curious"},
                summary="Alice is curious.",
                confidence=0.8,
            )
        style = repository.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=None,
            domain="style",
            category="communication_style",
            subcategory="",
            canonical_key="alice:style:communication_style:humorous",
            payload={"tone": "humorous", "generation_guidance": "Use light humor."},
            summary="Alice often communicates humorously.",
            confidence=0.6,
        )

    assert style["domain"] == "style"


def test_add_candidate_rejects_invalid_payload_shape(settings):
    repository = CandidateRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn)
        with pytest.raises(ValueError, match="payload.city"):
            repository.add_candidate(
                conn,
                workspace_slug="default",
                person_id=int(person["id"]),
                source_id=source_id,
                conversation_id=None,
                chunk_kind="conversation",
                chunk_id=None,
                domain="biography",
                category="residence",
                subcategory="",
                canonical_key="alice:biography:residence:lisbon",
                payload={"place": "Lisbon"},
                summary="Alice lives in Lisbon.",
                confidence=0.8,
            )

def test_add_candidate_accepts_p0b_domain(settings):
    repository = CandidateRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn)
        candidate = repository.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=3,
            domain="work",
            category="employment",
            subcategory="",
            canonical_key="alice:work:employment:engineer",
            payload={"title": "Engineer"},
            summary="Alice works as engineer.",
            confidence=0.78,
        )

    assert candidate["domain"] == "work"
    assert candidate["category"] == "employment"


def test_list_candidates_filters_by_status_and_domain(settings):
    repository = CandidateRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn)
        first = repository.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=1,
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:lisbon",
            payload={"city": "Lisbon"},
            summary="Alice lives in Lisbon.",
            confidence=0.9,
        )
        second = repository.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=2,
            domain="preferences",
            category="preference",
            subcategory="",
            canonical_key="alice:preferences:preference:tea",
            payload={"value": "tea"},
            summary="Alice likes tea.",
            confidence=0.8,
            reason="speaker_unresolved",
        )
        repository.mark_candidate_status(
            conn,
            candidate_id=int(second["id"]),
            candidate_status="needs_review",
            reason="speaker_unresolved",
        )

        results = repository.list_candidates(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate_status="needs_review",
            domain="preferences",
        )

    assert [item["id"] for item in results] == [int(second["id"])]
    assert results[0]["candidate_status"] == "needs_review"
    assert results[0]["domain"] == "preferences"
    assert int(first["id"]) not in [item["id"] for item in results]


def test_candidate_rejects_forbidden_transition(settings):
    repository = CandidateRepository()

    with get_connection(settings.db_path) as conn:
        person, source_id = _seed_person_and_source(conn)
        candidate = repository.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=7,
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:porto",
            payload={"city": "Porto"},
            summary="Alice lives in Porto.",
            confidence=0.7,
        )
        with pytest.raises(ValueError, match="Cannot transition candidate from extracted_candidate to published"):
            repository.mark_candidate_status(
                conn,
                candidate_id=int(candidate["id"]),
                candidate_status="published",
            )

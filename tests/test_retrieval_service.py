from __future__ import annotations

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.models.retrieval import RetrievalRequest
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService
from memco.services.retrieval_service import RetrievalService


def test_retrieve_returns_matching_fact(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/bob.md",
            source_type="note",
            origin_uri="/tmp/bob.md",
            title="bob",
            sha256="def456",
            parsed_text="Bob lives in Berlin.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="bob:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Bob lives in Berlin.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob lives in Berlin.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="bob",
                query="Where does Bob live?",
            ),
        )

    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].payload["city"] == "Berlin"
    assert len(result.hits[0].evidence) == 1
    assert result.hits[0].evidence[0]["quote_text"] == "Bob lives in Berlin."


def test_retrieve_filters_by_domain(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/bob-2.md",
            source_type="note",
            origin_uri="/tmp/bob-2.md",
            title="bob-2",
            sha256="def457",
            parsed_text="Bob lives in Berlin. Bob likes tea.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="bob:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Bob lives in Berlin.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob lives in Berlin.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="bob:preferences:preference:tea",
                payload={"value": "tea"},
                summary="Bob likes tea.",
                confidence=0.88,
                observed_at="2026-04-21T10:01:00Z",
                source_id=source_id,
                quote_text="Bob likes tea.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="bob",
                query="What does Bob like?",
                domain="preferences",
            ),
        )

    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].domain == "preferences"


def test_retrieve_supports_history_queries(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Bob",
            slug="bob",
            person_type="human",
            aliases=["Bob"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/bob-history.md",
            source_type="note",
            origin_uri="/tmp/bob-history.md",
            title="bob-history",
            sha256="def458",
            parsed_text="Bob lived in Berlin and later moved to Lisbon.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="bob:biography:residence:berlin",
                payload={"city": "Berlin"},
                summary="Bob lives in Berlin.",
                confidence=0.9,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob lived in Berlin.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="bob:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Bob lives in Lisbon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob moved to Lisbon.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="bob",
                query="Where did Bob live before Lisbon?",
            ),
        )

    assert result.support_level == "full"
    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].payload["city"] == "Berlin"
    assert result.hits[0].status == "superseded"


def test_retrieve_marks_partial_support_for_mixed_claims(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-partial.md",
            source_type="note",
            origin_uri="/tmp/alice-partial.md",
            title="alice-partial",
            sha256="def459",
            parsed_text="Alice lives in Lisbon.",
        )
        consolidation.add_fact(
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
                quote_text="Alice lives in Lisbon.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Does Alice live in Lisbon and work at Stripe?",
            ),
        )

    assert result.support_level == "partial"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["city"] == "Lisbon"
    assert any("Stripe" in item for item in result.unsupported_claims)

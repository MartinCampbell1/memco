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

    assert result.support_level == "supported"
    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].payload["city"] == "Berlin"
    assert result.hits[0].status == "superseded"


def test_retrieve_supports_when_queries_with_event_at(settings):
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
            source_path="var/raw/bob-when-event.md",
            source_type="note",
            origin_uri="/tmp/bob-when-event.md",
            title="bob-when-event",
            sha256="def458a",
            parsed_text="Bob attended PyCon in 2025.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="bob:experiences:event:pycon",
                payload={"event": "PyCon"},
                summary="Bob attended PyCon.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                event_at="2025",
                source_id=source_id,
                quote_text="Bob attended PyCon in 2025.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="bob",
                query="When did Bob attend PyCon?",
            ),
        )

    assert result.support_level == "supported"
    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].event_at == "2025"
    assert result.planner is not None
    assert result.planner.temporal_mode == "when"


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


def test_retrieve_refuses_subject_binding_mismatch(settings):
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
        fact_repo.upsert_person(
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
            source_path="var/raw/alice-subject-mismatch.md",
            source_type="note",
            origin_uri="/tmp/alice-subject-mismatch.md",
            title="alice-subject-mismatch",
            sha256="def460",
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
                query="Where does Bob live?",
            ),
        )

    assert result.support_level == "unsupported"
    assert result.unsupported_premise_detected is True
    assert result.hits == []
    assert result.fallback_hits == []
    assert result.unsupported_claims == ["Query subject does not match requested person."]


def test_retrieve_marks_contradicted_support_for_conflicting_current_fact(settings):
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
            source_path="var/raw/alice-contradicted.md",
            source_type="note",
            origin_uri="/tmp/alice-contradicted.md",
            title="alice-contradicted",
            sha256="def461",
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
                query="Does Alice live in Berlin?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["city"] == "Lisbon"
    assert any("Berlin" in item for item in result.unsupported_claims)


def test_retrieve_marks_contradicted_support_for_conflicting_preference_fact(settings):
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
            source_path="var/raw/alice-preference-contradicted.md",
            source_type="note",
            origin_uri="/tmp/alice-preference-contradicted.md",
            title="alice-preference-contradicted",
            sha256="def462",
            parsed_text="Alice prefers tea.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="preferences",
                category="preference",
                canonical_key="alice:preferences:preference:tea",
                payload={"value": "tea", "polarity": "like", "is_current": True},
                summary="Alice prefers tea.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice prefers tea.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Does Alice prefer coffee?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["value"] == "tea"
    assert any("coffee" in item.lower() for item in result.unsupported_claims)


def test_retrieve_marks_contradicted_support_for_conflicting_event_claim(settings):
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
            source_path="var/raw/alice-event-contradicted.md",
            source_type="note",
            origin_uri="/tmp/alice-event-contradicted.md",
            title="alice-event-contradicted",
            sha256="def463",
            parsed_text="Alice attended PyCon in 2026.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon",
                payload={"event": "PyCon", "temporal_anchor": "2026"},
                summary="Alice attended PyCon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice attended PyCon in 2026.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Did Alice attend JSConf?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["event"] == "PyCon"
    assert any("JSConf" in item for item in result.unsupported_claims)


def test_retrieve_marks_contradicted_support_for_conflicting_event_date_claim(settings):
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
            source_path="var/raw/alice-event-date-contradicted.md",
            source_type="note",
            origin_uri="/tmp/alice-event-date-contradicted.md",
            title="alice-event-date-contradicted",
            sha256="def464",
            parsed_text="Alice attended PyCon in 2026.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon",
                payload={"event": "PyCon", "temporal_anchor": "2026"},
                summary="Alice attended PyCon.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice attended PyCon in 2026.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Did Alice attend PyCon in 2025?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["event"] == "PyCon"
    assert any("2025" in item for item in result.unsupported_claims)


def test_retrieve_marks_contradicted_support_for_conflicting_relation_fact(settings):
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
            source_path="var/raw/alice-relation-contradicted.md",
            source_type="note",
            origin_uri="/tmp/alice-relation-contradicted.md",
            title="alice-relation-contradicted",
            sha256="def465",
            parsed_text="Bob is Alice's friend.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="social_circle",
                category="friend",
                canonical_key="alice:social_circle:friend:bob",
                payload={"relation": "friend", "target_label": "Bob"},
                summary="Alice says Bob is their friend.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob is my friend.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Is Bob Alice's brother?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["target_label"] == "Bob"
    assert any("brother" in item.lower() for item in result.unsupported_claims)


def test_retrieve_prefers_field_specific_match_over_summary_only_match(settings):
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
            source_path="var/raw/alice-work-fields.md",
            source_type="note",
            origin_uri="/tmp/alice-work-fields.md",
            title="alice-work-fields",
            sha256="def460",
            parsed_text="Alice works at OpenAI and uses Python.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="org",
                canonical_key="alice:work:org:openai",
                payload={"org": "OpenAI", "is_current": True},
                summary="Alice works at OpenAI.",
                confidence=0.8,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice works at OpenAI.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="tool",
                canonical_key="alice:work:tool:python",
                payload={"tool": "Python"},
                summary="Alice uses Python every day at work.",
                confidence=0.8,
                observed_at="2026-04-21T10:01:00Z",
                source_id=source_id,
                quote_text="Alice uses Python.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="What tool does Alice use?",
                domain="work",
            ),
        )

    assert len(result.hits) >= 1
    assert result.hits[0].category == "tool"
    assert result.hits[0].payload["tool"] == "Python"


def test_retrieve_applies_recency_penalty_for_current_mode(settings):
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
            source_path="var/raw/alice-org-recency.md",
            source_type="note",
            origin_uri="/tmp/alice-org-recency.md",
            title="alice-org-recency",
            sha256="def461",
            parsed_text="Alice worked at Stripe and now works at OpenAI.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="org",
                canonical_key="alice:work:org:stripe",
                payload={"org": "Stripe", "is_current": False},
                summary="Alice used to work at Stripe.",
                confidence=0.96,
                observed_at="2025-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice worked at Stripe.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="org",
                canonical_key="alice:work:org:openai",
                payload={"org": "OpenAI", "is_current": True},
                summary="Alice now works at OpenAI.",
                confidence=0.8,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice now works at OpenAI.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Where does Alice work now?",
                domain="work",
                temporal_mode="current",
            ),
        )

    assert len(result.hits) >= 1
    assert result.hits[0].payload["org"] == "OpenAI"


def test_retrieve_prefers_better_evidence_quality_when_scores_tie(settings):
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
            source_path="var/raw/alice-food.md",
            source_type="note",
            origin_uri="/tmp/alice-food.md",
            title="alice-food",
            sha256="def462",
            parsed_text="Alice likes tea and coffee.",
        )
        tea = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="tool",
                canonical_key="alice:work:tool:python",
                payload={"tool": "Python"},
                summary="Alice uses Python.",
                confidence=0.8,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice uses Python.",
            ),
        )
        coffee = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="skill",
                canonical_key="alice:work:skill:python",
                payload={"skill": "Python"},
                summary="Alice knows Python.",
                confidence=0.8,
                observed_at="2026-04-21T10:01:00Z",
                source_id=source_id,
                quote_text="Alice knows Python.",
            ),
        )
        conn.execute(
            "UPDATE memory_evidence SET source_confidence = 0.3 WHERE fact_id = ?",
            (int(coffee["id"]),),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="What tool does Alice use?",
                domain="work",
            ),
        )

    assert len(result.hits) >= 2
    assert result.hits[0].category == "tool"
    assert result.hits[0].payload["tool"] == "Python"


def test_retrieve_keeps_low_confidence_field_match_amid_high_confidence_noise(settings):
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
            source_path="var/raw/alice-noise.md",
            source_type="note",
            origin_uri="/tmp/alice-noise.md",
            title="alice-noise",
            sha256="def463",
            parsed_text="Alice works with many tools.",
        )
        for index in range(40):
            consolidation.add_fact(
                conn,
                MemoryFactInput(
                    workspace="default",
                    person_id=int(person["id"]),
                    domain="work",
                    category="tool",
                    canonical_key=f"alice:work:tool:distractor-{index}",
                    payload={"tool": f"Distractor{index}"},
                    summary=f"Alice uses Distractor{index}.",
                    confidence=0.99,
                    observed_at="2026-04-21T10:00:00Z",
                    source_id=source_id,
                    quote_text=f"Alice uses Distractor{index}.",
                ),
            )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="tool",
                canonical_key="alice:work:tool:python",
                payload={"tool": "Python"},
                summary="Alice uses Python.",
                confidence=0.55,
                observed_at="2026-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Alice uses Python.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="What tool does Alice use for Python?",
                domain="work",
                limit=8,
            ),
        )

    assert any(hit.payload.get("tool") == "Python" for hit in result.hits)


def test_retrieve_applies_stale_penalty_for_older_active_facts(settings):
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
            source_path="var/raw/alice-stale.md",
            source_type="note",
            origin_uri="/tmp/alice-stale.md",
            title="alice-stale",
            sha256="def464",
            parsed_text="Alice uses Python and Rust.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="skill",
                canonical_key="alice:work:skill:python",
                payload={"skill": "Python"},
                summary="Alice knows Python.",
                confidence=0.8,
                observed_at="2024-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice knows Python.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="skill",
                canonical_key="alice:work:skill:rust",
                payload={"skill": "Rust"},
                summary="Alice knows Rust.",
                confidence=0.8,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice knows Rust.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="What skill does Alice have?",
                domain="work",
            ),
        )

    assert len(result.hits) >= 2
    assert result.hits[0].payload["skill"] == "Rust"

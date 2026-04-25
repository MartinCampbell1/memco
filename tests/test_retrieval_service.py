from __future__ import annotations

import pytest

from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.models.retrieval import RetrievalRequest
from memco.repositories.conversation_repository import ConversationRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.retrievers import build_domain_retrievers
from memco.services.consolidation_service import ConsolidationService
from memco.services.retrieval_service import RetrievalService


def _seed_alice_work_fact(settings, *, category: str, payload: dict, summary: str) -> None:
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    value = next(iter(payload.values()))
    key_value = str(value).lower().replace(" ", "-")
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
            source_path=f"var/raw/alice-work-{category}-{key_value}.md",
            source_type="note",
            origin_uri=f"/tmp/alice-work-{category}-{key_value}.md",
            title=f"alice-work-{category}-{key_value}",
            sha256=f"alice-work-{category}-{key_value}",
            parsed_text=summary,
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category=category,
                canonical_key=f"alice:work:{category}:{key_value}",
                payload=payload,
                summary=summary,
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=summary,
            ),
        )


def _seed_alice_experience_fact(settings, *, payload: dict, summary: str, event_at: str = "") -> None:
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    key_value = str(payload.get("event", "event")).lower().replace(" ", "-")
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
            source_path=f"var/raw/alice-experience-{key_value}.md",
            source_type="note",
            origin_uri=f"/tmp/alice-experience-{key_value}.md",
            title=f"alice-experience-{key_value}",
            sha256=f"alice-experience-{key_value}",
            parsed_text=summary,
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key=f"alice:experiences:event:{key_value}",
                payload=payload,
                summary=summary,
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                event_at=event_at,
                source_id=source_id,
                quote_text=summary,
            ),
        )


def _seed_alice_conversation_chunk(settings, *, text: str) -> None:
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    conversation_repo = ConversationRepository()
    text_key = str(sum(ord(char) for char in text))
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
            source_path="var/raw/alice-fallback-chat.json",
            source_type="conversation",
            origin_uri="/tmp/alice-fallback-chat.json",
            title="alice-fallback-chat",
            sha256=f"alice-fallback-chat-{text_key}",
            parsed_text=text,
        )
        conversation_id = conversation_repo.upsert_conversation(
            conn,
            workspace_slug="default",
            source_id=source_id,
            conversation_uid=f"alice-fallback-chat-{text_key}",
            title="alice fallback chat",
            started_at="2026-04-21T10:00:00Z",
            ended_at="2026-04-21T10:00:00Z",
        )
        conversation_repo.replace_messages(
            conn,
            conversation_id=conversation_id,
            messages=[
                {
                    "role": "user",
                    "speaker_label": "Alice",
                    "speaker_key": "alice",
                    "speaker_person_id": int(person["id"]),
                    "occurred_at": "2026-04-21T10:00:00Z",
                    "text": text,
                }
            ],
        )
        conversation_repo.replace_chunks(
            conn,
            conversation_id=conversation_id,
            source_id=source_id,
            chunks=[
                {
                    "start_message_index": 0,
                    "end_message_index": 0,
                    "text": text,
                    "token_count": len(text.split()),
                    "locator": {"message_index": 0},
                }
            ],
        )


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


@pytest.mark.parametrize(
    ("domain", "category", "canonical_key", "payload", "summary", "query", "expected_key"),
    [
        (
            "biography",
            "health",
            "alice:biography:health:gluten",
            {"health_fact": "gluten sensitivity", "status": "current"},
            "Alice has a current gluten sensitivity.",
            "What health note mentions gluten?",
            "health_fact",
        ),
        (
            "experiences",
            "event",
            "alice:experiences:event:pycon-berlin",
            {"event": "PyCon", "location": "Berlin", "outcome": "won the hackathon", "intensity": 0.8},
            "Alice attended PyCon in Berlin and won the hackathon.",
            "What happened at PyCon in Berlin?",
            "location",
        ),
        (
            "preferences",
            "preference",
            "alice:preferences:preference:tea-focus",
            {"value": "tea", "preference_domain": "food", "preference_category": "drink", "context": "focus"},
            "Alice likes tea when focusing.",
            "What does Alice like?",
            "value",
        ),
        (
            "social_circle",
            "friend",
            "alice:social_circle:friend:bob",
            {"relation": "friend", "target_label": "Bob", "target_person_id": None, "aliases": ["Bobby"], "valence": "positive"},
            "Alice says Bob is their friend.",
            "Who is Alice's friend Bobby?",
            "target_label",
        ),
        (
            "work",
            "engagement",
            "alice:work:engagement:memco-launch",
            {"engagement": "Memco launch", "role": "builder", "outcomes": ["private memory API"], "team": "solo"},
            "Alice is building the Memco launch engagement.",
            "What work engagement produced a private memory API?",
            "engagement",
        ),
    ],
)
def test_retrieve_matches_phase6_expanded_domain_fields(settings, domain, category, canonical_key, payload, summary, query, expected_key):
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
            source_path=f"var/raw/{canonical_key.replace(':', '-')}.md",
            source_type="note",
            origin_uri=f"/tmp/{canonical_key.replace(':', '-')}.md",
            title=canonical_key.replace(":", "-"),
            sha256=canonical_key.replace(":", "-"),
            parsed_text=summary,
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain=domain,
                category=category,
                canonical_key=canonical_key,
                payload=payload,
                summary=summary,
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=summary,
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query=query,
                domain=domain,
                category=category,
            ),
        )

    assert result.support_level == "supported"
    assert len(result.hits) == 1
    assert expected_key in result.hits[0].payload


def test_work_tool_query_retrieves_tool_fact(settings):
    _seed_alice_work_fact(settings, category="tool", payload={"tool": "Python"}, summary="Alice uses Python.")
    _seed_alice_work_fact(settings, category="tool", payload={"tool": "Postgres"}, summary="Alice uses Postgres.")

    with get_connection(settings.db_path) as conn:
        result = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="What tools does Alice use?"),
        )

    assert result.support_level == "supported"
    assert result.answerable is True
    assert {hit.payload["tool"] for hit in result.hits} == {"Python", "Postgres"}
    assert all(hit.evidence for hit in result.hits)


def test_work_tool_yes_no_supported_and_false_premise_refused(settings):
    _seed_alice_work_fact(settings, category="tool", payload={"tool": "Python"}, summary="Alice uses Python.")
    _seed_alice_work_fact(settings, category="tool", payload={"tool": "Postgres"}, summary="Alice uses Postgres.")

    with get_connection(settings.db_path) as conn:
        python_result = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Does Alice use Python?"),
        )
        ruby_result = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Does Alice use Ruby?"),
        )

    assert python_result.support_level == "supported"
    assert python_result.answerable is True
    assert python_result.hits[0].payload["tool"] == "Python"
    assert ruby_result.support_level == "contradicted"
    assert ruby_result.answerable is False
    assert ruby_result.must_not_use_as_fact is True
    assert any("Ruby" in claim for claim in ruby_result.unsupported_claims)


def test_work_project_and_generic_work_queries_use_work_category_fallback(settings):
    _seed_alice_work_fact(settings, category="project", payload={"project": "Project Phoenix"}, summary="Alice launched Project Phoenix.")
    _seed_alice_work_fact(settings, category="tool", payload={"tool": "Python"}, summary="Alice uses Python.")

    with get_connection(settings.db_path) as conn:
        project_result = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="What project did Alice launch?"),
        )
        generic_result = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="What does Alice do for work?"),
        )

    assert project_result.support_level == "supported"
    assert project_result.hits[0].payload["project"] == "Project Phoenix"
    assert generic_result.support_level == "supported"
    assert {hit.category for hit in generic_result.hits} >= {"project", "tool"}


def test_experience_accident_queries_are_supported_with_evidence(settings):
    _seed_alice_experience_fact(
        settings,
        payload={
            "event": "serious car accident",
            "summary": "Alice had a serious car accident during a family road trip to the Grand Canyon.",
            "temporal_anchor": "October 2023",
            "location": "Grand Canyon",
            "outcome": "pause pottery",
            "valence": "negative",
            "intensity": "high",
        },
        summary="Alice had a serious car accident during a family road trip to the Grand Canyon and had to pause pottery.",
        event_at="October 2023",
    )

    with get_connection(settings.db_path) as conn:
        happened = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="What happened to Alice in October 2023?"),
        )
        when = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="When did Alice have the accident?"),
        )
        why = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Why did Alice pause pottery?"),
        )

    for result in (happened, when, why):
        assert result.support_level == "supported"
        assert result.answerable is True
        assert result.hits
        assert result.hits[0].evidence
    assert when.hits[0].event_at == "October 2023"


def test_experience_false_premise_accident_is_contradicted(settings):
    _seed_alice_experience_fact(
        settings,
        payload={"event": "serious car accident", "temporal_anchor": "October 2023"},
        summary="Alice had a serious car accident in October 2023.",
        event_at="October 2023",
    )

    with get_connection(settings.db_path) as conn:
        result = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Was Alice in a ski accident?"),
        )

    assert result.support_level == "contradicted"
    assert result.answerable is False
    assert result.must_not_use_as_fact is True
    assert any("ski accident" in claim.lower() for claim in result.unsupported_claims)


def test_relationship_query_retrieves_biography_family_fallback(settings):
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
            source_path="var/raw/alice-family.md",
            source_type="note",
            origin_uri="/tmp/alice-family.md",
            title="alice-family",
            sha256="alice-family-sha",
            parsed_text="Alice's sister is Maria.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="family",
                subcategory="sister",
                canonical_key="alice:biography:family:sister:maria",
                payload={"relation": "sister", "name": "Maria"},
                summary="Alice's sister is Maria.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice's sister is Maria.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Who is Alice's sister?",
            ),
        )

    assert result.support_level == "supported"
    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].domain == "biography"
    assert result.hits[0].category == "family"
    assert result.hits[0].payload["name"] == "Maria"


@pytest.mark.parametrize(
    ("relation", "target_name", "domain", "category"),
    [
        ("sister", "Maria", "biography", "family"),
        ("brother", "Noah", "biography", "family"),
        ("mother", "Emma", "biography", "family"),
        ("father", "Victor", "biography", "family"),
        ("partner", "Riley", "biography", "family"),
        ("spouse", "Sam", "biography", "family"),
        ("friend", "Bob", "social_circle", "friend"),
        ("colleague", "Dana", "social_circle", "colleague"),
    ],
)
def test_relationship_queries_bridge_family_and_social_taxonomy(settings, relation, target_name, domain, category):
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
            source_path=f"var/raw/alice-{relation}.md",
            source_type="note",
            origin_uri=f"/tmp/alice-{relation}.md",
            title=f"alice-{relation}",
            sha256=f"alice-{relation}-sha",
            parsed_text=f"Alice's {relation} is {target_name}.",
        )
        payload = (
            {"relation": relation, "name": target_name}
            if domain == "biography"
            else {"relation": relation, "target_label": target_name, "target_person_id": None, "is_current": True}
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain=domain,
                category=category,
                subcategory=relation if domain == "biography" else "",
                canonical_key=f"alice:{domain}:{category}:{relation}:{target_name.lower()}",
                payload=payload,
                summary=f"Alice's {relation} is {target_name}.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=f"Alice's {relation} is {target_name}.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query=f"Who is Alice's {relation}?",
            ),
        )

    assert result.support_level == "supported"
    assert result.answerable is True
    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    target_field = "name" if domain == "biography" else "target_label"
    assert result.hits[0].payload[target_field] == target_name


def test_relationship_named_false_premise_contradicts_family_fact(settings):
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
            source_path="var/raw/alice-sister-contradiction.md",
            source_type="note",
            origin_uri="/tmp/alice-sister-contradiction.md",
            title="alice-sister-contradiction",
            sha256="alice-sister-contradiction-sha",
            parsed_text="Alice's sister is Maria.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="family",
                subcategory="sister",
                canonical_key="alice:biography:family:sister:maria",
                payload={"relation": "sister", "name": "Maria"},
                summary="Alice's sister is Maria.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice's sister is Maria.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Does Alice have a sister named Olga?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.answerable is False
    assert result.must_not_use_as_fact is True
    assert result.refusal_category == "contradicted_by_memory"
    assert any("Olga" in item for item in result.unsupported_claims)
    assert result.safe_known_facts == ["Alice's sister is Maria."]


@pytest.mark.parametrize(
    ("stored_relation", "query"),
    [
        ("spouse", "Who is Alice's wife?"),
        ("wife", "Who is Alice's spouse?"),
        ("husband", "Who is Alice's spouse?"),
    ],
)
def test_relationship_alias_queries_match_canonical_relation(settings, stored_relation, query):
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
            source_path=f"var/raw/alice-{stored_relation}-alias.md",
            source_type="note",
            origin_uri=f"/tmp/alice-{stored_relation}-alias.md",
            title=f"alice-{stored_relation}-alias",
            sha256=f"alice-{stored_relation}-alias-sha",
            parsed_text=f"Alice's {stored_relation} is Riley.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="family",
                subcategory=stored_relation,
                canonical_key=f"alice:biography:family:{stored_relation}:riley",
                payload={"relation": stored_relation, "name": "Riley"},
                summary=f"Alice's {stored_relation} is Riley.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=f"Alice's {stored_relation} is Riley.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query=query,
            ),
        )

    assert result.support_level == "supported"
    assert result.answerable is True
    assert result.unsupported_premise_detected is False
    assert len(result.hits) == 1
    assert result.hits[0].payload["name"] == "Riley"


def test_relationship_query_filters_to_requested_relation_in_populated_graph(settings):
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
            source_path="var/raw/alice-family-populated.md",
            source_type="note",
            origin_uri="/tmp/alice-family-populated.md",
            title="alice-family-populated",
            sha256="alice-family-populated-sha",
            parsed_text="Alice's sister is Maria. Alice's brother is Noah. Alice's spouse is Riley.",
        )
        for relation, target in (("sister", "Maria"), ("brother", "Noah"), ("spouse", "Riley")):
            consolidation.add_fact(
                conn,
                MemoryFactInput(
                    workspace="default",
                    person_id=int(person["id"]),
                    domain="biography",
                    category="family",
                    subcategory=relation,
                    canonical_key=f"alice:biography:family:{relation}:{target.lower()}",
                    payload={"relation": relation, "name": target},
                    summary=f"Alice's {relation} is {target}.",
                    confidence=0.95,
                    observed_at="2026-04-21T10:00:00Z",
                    source_id=source_id,
                    quote_text=f"Alice's {relation} is {target}.",
                ),
            )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Who is Alice's sister?",
            ),
        )

    assert result.support_level == "supported"
    assert len(result.hits) == 1
    assert result.hits[0].payload["name"] == "Maria"
    assert result.safe_known_facts == ["Alice's sister is Maria."]


def test_relationship_false_premise_filters_confirmed_fact_to_requested_relation(settings):
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
            source_path="var/raw/alice-family-populated-contradiction.md",
            source_type="note",
            origin_uri="/tmp/alice-family-populated-contradiction.md",
            title="alice-family-populated-contradiction",
            sha256="alice-family-populated-contradiction-sha",
            parsed_text="Alice's sister is Maria. Alice's brother is Noah. Alice's spouse is Riley.",
        )
        for relation, target in (("sister", "Maria"), ("brother", "Noah"), ("spouse", "Riley")):
            consolidation.add_fact(
                conn,
                MemoryFactInput(
                    workspace="default",
                    person_id=int(person["id"]),
                    domain="biography",
                    category="family",
                    subcategory=relation,
                    canonical_key=f"alice:biography:family:{relation}:{target.lower()}",
                    payload={"relation": relation, "name": target},
                    summary=f"Alice's {relation} is {target}.",
                    confidence=0.95,
                    observed_at="2026-04-21T10:00:00Z",
                    source_id=source_id,
                    quote_text=f"Alice's {relation} is {target}.",
                ),
            )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Does Alice have a sister named Olga?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.answerable is False
    assert len(result.hits) == 1
    assert result.hits[0].payload["name"] == "Maria"
    assert result.safe_known_facts == ["Alice's sister is Maria."]
    assert all("Noah" not in fact and "Riley" not in fact for fact in result.safe_known_facts)


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


def test_retrieve_supports_when_queries_with_valid_from_only(settings):
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
            source_path="var/raw/bob-when-valid-from.md",
            source_type="note",
            origin_uri="/tmp/bob-when-valid-from.md",
            title="bob-when-valid-from",
            sha256="def458b",
            parsed_text="Bob has lived in Lisbon since 2024-05-01.",
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
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                valid_from="2024-05-01",
                source_id=source_id,
                quote_text="Bob has lived in Lisbon since 2024-05-01.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="bob",
                query="When did Bob start living in Lisbon?",
            ),
        )

    assert result.support_level == "supported"
    assert len(result.hits) == 1
    assert result.hits[0].event_at == ""
    assert result.hits[0].valid_from == "2024-05-01"
    assert result.planner is not None
    assert result.planner.temporal_mode == "when"


def test_retrieve_supports_when_queries_with_observed_at_only(settings):
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
            source_path="var/raw/bob-when-observed.md",
            source_type="note",
            origin_uri="/tmp/bob-when-observed.md",
            title="bob-when-observed",
            sha256="def458c",
            parsed_text="Bob attended WebSummit.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="bob:experiences:event:websummit",
                payload={"event": "WebSummit"},
                summary="Bob attended WebSummit.",
                confidence=0.82,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Bob attended WebSummit.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="bob",
                query="When did Bob attend WebSummit?",
            ),
        )

    assert result.support_level == "supported"
    assert len(result.hits) == 1
    assert result.hits[0].event_at == ""
    assert result.hits[0].valid_from == ""
    assert result.hits[0].observed_at == "2026-04-21T10:00:00Z"


def test_retrieve_marks_ambiguous_support_for_conflicting_event_dates_on_when_queries(settings):
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
            source_path="var/raw/alice-conflicting-event-dates.md",
            source_type="note",
            origin_uri="/tmp/alice-conflicting-event-dates.md",
            title="alice-conflicting-event-dates",
            sha256="def458d",
            parsed_text="Alice attended PyCon.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon-2025",
                payload={"event": "PyCon"},
                summary="Alice attended PyCon.",
                confidence=0.84,
                observed_at="2026-04-21T10:00:00Z",
                event_at="2025",
                source_id=source_id,
                quote_text="Alice attended PyCon in 2025.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="experiences",
                category="event",
                canonical_key="alice:experiences:event:pycon-2026",
                payload={"event": "PyCon"},
                summary="Alice attended PyCon.",
                confidence=0.83,
                observed_at="2026-04-21T10:01:00Z",
                event_at="2026",
                source_id=source_id,
                quote_text="Alice attended PyCon in 2026.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="When did Alice attend PyCon?",
            ),
        )

    assert result.support_level == "ambiguous"
    assert any("conflicting temporal evidence" in item.lower() for item in result.unsupported_claims)


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
    assert result.answerable is False
    assert result.must_not_use_as_fact is True
    assert result.refusal_category == "unsupported_no_evidence"
    assert result.unsupported_premise_detected is True
    assert len(result.hits) == 1
    assert result.hits[0].payload["city"] == "Lisbon"
    assert any("Stripe" in item for item in result.unsupported_claims)
    assert result.safe_known_facts == ["Alice lives in Lisbon."]


def test_retrieve_marks_contradicted_support_for_conflicting_employer_fact(settings):
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
            source_path="var/raw/alice-work-employer.md",
            source_type="note",
            origin_uri="/tmp/alice-work-employer.md",
            title="alice-work-employer",
            sha256="def459-work",
            parsed_text="Alice works as a software engineer at Acme Robotics.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="work",
                category="employment",
                canonical_key="alice:work:employment:acme-robotics",
                payload={"role": "software engineer", "org": "Acme Robotics", "is_current": True},
                summary="Alice works as software engineer at Acme Robotics.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice works as a software engineer at Acme Robotics.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Does Alice work at Stripe?",
            ),
        )

    assert result.support_level == "contradicted"
    assert result.answerable is False
    assert result.must_not_use_as_fact is True
    assert result.refusal_category == "contradicted_by_memory"
    assert result.unsupported_premise_detected is True
    assert any("Stripe" in item for item in result.unsupported_claims)
    assert result.safe_known_facts == ["Alice works as software engineer at Acme Robotics."]


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
    assert result.answerable is False
    assert result.must_not_use_as_fact is True
    assert result.refusal_category == "subject_mismatch"
    assert result.unsupported_premise_detected is True
    assert result.hits == []
    assert result.fallback_hits == []
    assert result.unsupported_claims == ["Query subject does not match requested person."]


def test_retrieve_does_not_use_raw_fallback_for_explicit_domain_mismatch(settings):
    _seed_alice_conversation_chunk(settings, text="Alice: I live in Lisbon.")
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                domain="work",
                query="Where does Alice live?",
            ),
        )

    assert result.hits == []
    assert result.fallback_hits == []
    assert result.support_level == "unsupported"
    assert result.answerable is False


def test_retrieve_does_not_use_raw_fallback_for_false_premise_query(settings):
    _seed_alice_conversation_chunk(settings, text="Alice: I live in Lisbon.")
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Does Alice live in Berlin?",
            ),
        )

    assert result.hits == []
    assert result.fallback_hits == []
    assert result.support_level == "unsupported"
    assert result.answerable is False
    assert any("Berlin" in claim for claim in result.unsupported_claims)


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


def test_domain_retrievers_expose_category_rag_contracts():
    retrievers = build_domain_retrievers()

    assert {"biography", "preferences", "social_circle", "work", "experiences", "psychometrics"} <= set(retrievers)
    assert "city" in retrievers["biography"].payload_fields["residence"]
    assert "value" in retrievers["preferences"].payload_fields["preference"]
    assert "target_label" in retrievers["social_circle"].payload_fields["relationship"]
    assert "event_at" in retrievers["experiences"].payload_fields["event"]
    assert retrievers["psychometrics"].factual is False
    assert retrievers["work"].category_sequence("tool")[1] == "skill"


def test_relationship_residence_multi_hop_retrieves_related_person_residence(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        alice = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        maria = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Maria",
            slug="maria",
            person_type="human",
            aliases=["Maria"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/alice-maria-residence.md",
            source_type="note",
            origin_uri="/tmp/alice-maria-residence.md",
            title="alice-maria-residence",
            sha256="alice-maria-residence-sha",
            parsed_text="Alice's sister is Maria. Maria lives in Porto.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(alice["id"]),
                domain="biography",
                category="family",
                subcategory="sister",
                canonical_key="alice:biography:family:sister:maria",
                payload={"relation": "sister", "name": "Maria", "target_person_id": int(maria["id"])},
                summary="Alice's sister is Maria.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice's sister is Maria.",
            ),
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(maria["id"]),
                domain="biography",
                category="residence",
                canonical_key="maria:biography:residence:porto",
                payload={"city": "Porto"},
                summary="Maria lives in Porto.",
                confidence=0.95,
                observed_at="2026-04-21T10:05:00Z",
                source_id=source_id,
                quote_text="Maria lives in Porto.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Who is Alice's sister and where does she live?",
                limit=5,
            ),
        )

    assert result.support_level == "supported"
    assert result.answerable is True
    assert any(hit.category == "family" and hit.payload["name"] == "Maria" for hit in result.hits)
    assert any(hit.category == "residence" and hit.payload["city"] == "Porto" for hit in result.hits)


def test_relationship_residence_multi_hop_reports_missing_related_residence(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    retrieval = RetrievalService()

    with get_connection(settings.db_path) as conn:
        alice = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        maria = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Maria",
            slug="maria",
            person_type="human",
            aliases=["Maria"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/alice-maria-no-residence.md",
            source_type="note",
            origin_uri="/tmp/alice-maria-no-residence.md",
            title="alice-maria-no-residence",
            sha256="alice-maria-no-residence-sha",
            parsed_text="Alice's sister is Maria.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(alice["id"]),
                domain="biography",
                category="family",
                subcategory="sister",
                canonical_key="alice:biography:family:sister:maria",
                payload={"relation": "sister", "name": "Maria", "target_person_id": int(maria["id"])},
                summary="Alice's sister is Maria.",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice's sister is Maria.",
            ),
        )
        result = retrieval.retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Who is Alice's sister and where does she live?",
                limit=5,
            ),
        )

    assert result.support_level == "partial"
    assert result.answerable is False
    assert any(hit.category == "family" and hit.payload["name"] == "Maria" for hit in result.hits)
    assert any("Maria" in claim for claim in result.unsupported_claims)

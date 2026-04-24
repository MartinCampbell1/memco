from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


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


def test_chat_returns_refusal_without_memory(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["answerable"] is False
    assert payload["must_not_use_as_fact"] is True
    assert payload["used_fact_ids"] == []
    assert payload["used_evidence_ids"] == []
    assert payload["agent_response"]["answerable"] is False
    assert payload["agent_response"]["must_not_use_as_fact"] is True
    assert payload["answer"] == "I don't have confirmed memory evidence for that."


def test_chat_returns_answer_with_memory(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice.md",
            source_type="note",
            origin_uri="/tmp/alice.md",
            title="alice",
            sha256="ghi789",
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
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is False
    assert payload["answerable"] is True
    assert payload["must_not_use_as_fact"] is False
    assert "Lisbon" in payload["answer"]
    assert len(payload["fact_ids"]) == 1
    assert payload["fact_ids"] == [payload["retrieval"]["hits"][0]["fact_id"]]
    assert len(payload["evidence_ids"]) == 1
    assert payload["evidence_ids"][0] == payload["retrieval"]["hits"][0]["evidence"][0]["evidence_id"]
    assert payload["used_fact_ids"] == payload["fact_ids"]
    assert payload["used_evidence_ids"] == payload["evidence_ids"]
    assert payload["agent_response"]["answerable"] is True
    assert payload["agent_response"]["must_not_use_as_fact"] is False
    assert payload["agent_response"]["used_fact_ids"] == payload["fact_ids"]
    assert payload["agent_response"]["used_evidence_ids"] == payload["evidence_ids"]


def test_chat_does_not_answer_from_unpublished_candidates(monkeypatch, settings):
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
            source_path="var/raw/alice-candidate-only.md",
            source_type="note",
            origin_uri="/tmp/alice-candidate-only.md",
            title="alice-candidate-only",
            sha256="alice-candidate-only",
            parsed_text="Alice lives in Porto.",
        )
        candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="note",
            chunk_id=None,
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="alice:biography:residence:porto:candidate-only",
            payload={"city": "Porto"},
            summary="Alice lives in Porto.",
            confidence=0.95,
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Alice live?", "actor": _actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["answerable"] is False
    assert payload["must_not_use_as_fact"] is True
    assert payload["fact_ids"] == []
    assert payload["evidence_ids"] == []
    assert "Porto" not in payload["answer"]


def test_chat_answers_work_tool_questions_and_refuses_false_tool_premise(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-tools.md",
            source_type="note",
            origin_uri="/tmp/alice-tools.md",
            title="alice-tools",
            sha256="alice-tools",
            parsed_text="Alice uses Python and Postgres.",
        )
        for tool in ("Python", "Postgres"):
            consolidation.add_fact(
                conn,
                MemoryFactInput(
                    workspace="default",
                    person_id=int(person["id"]),
                    domain="work",
                    category="tool",
                    canonical_key=f"alice:work:tool:{tool.lower()}",
                    payload={"tool": tool},
                    summary=f"Alice uses {tool}.",
                    source_kind="explicit",
                    confidence=0.9,
                    observed_at="2026-04-21T10:00:00Z",
                    source_id=source_id,
                    quote_text=f"Alice uses {tool}.",
                ),
            )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    supported = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "What tools does Alice use?", "actor": _actor(settings)},
    )
    false_premise = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Does Alice use Ruby?", "actor": _actor(settings)},
    )

    assert supported.status_code == 200
    supported_payload = supported.json()
    assert supported_payload["refused"] is False
    assert supported_payload["support_level"] == "supported"
    assert "Python" in supported_payload["answer"]
    assert "Postgres" in supported_payload["answer"]
    assert supported_payload["fact_ids"]
    assert supported_payload["evidence_ids"]

    assert false_premise.status_code == 200
    false_payload = false_premise.json()
    assert false_payload["refused"] is True
    assert false_payload["answerable"] is False
    assert false_payload["must_not_use_as_fact"] is True
    assert false_payload["support_level"] == "contradicted"
    assert any("Ruby" in claim for claim in false_payload["unsupported_claims"])


def test_chat_supports_core_only_detail_policy(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-core-only-chat.md",
            source_type="note",
            origin_uri="/tmp/alice-core-only-chat.md",
            title="alice-core-only-chat",
            sha256="ghi789-core",
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
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "Where does Alice live?",
            "detail_policy": "core_only",
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["detail_policy"] == "core_only"
    assert payload["retrieval"]["detail_policy"] == "core_only"
    assert payload["hits"] == [
        {
            "fact_id": payload["fact_ids"][0],
            "domain": "biography",
            "category": "residence",
            "summary": "Alice lives in Lisbon.",
        }
    ]
    assert payload["retrieval"]["hits"] == [
        {
            "fact_id": payload["fact_ids"][0],
            "domain": "biography",
            "category": "residence",
            "summary": "Alice lives in Lisbon.",
            "status": "active",
            "confidence": 0.9,
        }
    ]


@pytest.mark.parametrize(
    "query",
    [
        "Does Alice live in Lisbon and work at Stripe?",
        "What do you know about Alice living in Lisbon and working at Stripe?",
    ],
)
def test_chat_refuses_partial_false_premise(monkeypatch, settings, query):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-partial-chat.md",
            source_type="note",
            origin_uri="/tmp/alice-partial-chat.md",
            title="alice-partial-chat",
            sha256="ghi790",
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
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": query,
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["answerable"] is False
    assert payload["must_not_use_as_fact"] is True
    assert "Lisbon" in payload["answer"]
    assert payload["retrieval"]["support_level"] == "partial"
    assert payload["retrieval"]["answerable"] is False
    assert payload["retrieval"]["must_not_use_as_fact"] is True
    assert payload["safe_known_facts"] == ["Alice lives in Lisbon."]
    assert payload["confirmed_facts"] == ["Alice lives in Lisbon."]
    assert payload["agent_response"]["answerable"] is False
    assert payload["agent_response"]["query"] == query
    assert payload["agent_response"]["target_person"]["slug"] == "alice"
    assert payload["agent_response"]["safe_known_facts"] == ["Alice lives in Lisbon."]
    assert payload["agent_response"]["confirmed_facts"][0]["summary"] == "Alice lives in Lisbon."
    assert payload["agent_response"]["evidence"][0]["evidence_id"] in payload["evidence_ids"]
    assert payload["agent_response"]["must_not_use_as_fact"] is True


def test_chat_refuses_subject_binding_mismatch(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-chat-subject-mismatch.md",
            source_type="note",
            origin_uri="/tmp/alice-chat-subject-mismatch.md",
            title="alice-chat-subject-mismatch",
            sha256="ghi792",
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
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Where does Bob live?", "actor": _actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["answer"] == "I don't have confirmed memory evidence for that."
    assert payload["retrieval"]["hits"] == []
    assert payload["retrieval"]["fallback_hits"] == []
    assert payload["retrieval"]["unsupported_claims"] == ["Query subject does not match requested person."]
    assert payload["retrieval"]["refusal_category"] == "subject_mismatch"


def test_chat_answers_biography_family_relationship_bridge(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-family-chat.md",
            source_type="note",
            origin_uri="/tmp/alice-family-chat.md",
            title="alice-family-chat",
            sha256="alice-family-chat-sha",
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
                source_kind="explicit",
                confidence=0.95,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice's sister is Maria.",
            ),
        )
        for relation, target in (("brother", "Noah"), ("spouse", "Riley")):
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
                    source_kind="explicit",
                    confidence=0.95,
                    observed_at="2026-04-21T10:00:00Z",
                    source_id=source_id,
                    quote_text=f"Alice's {relation} is {target}.",
                ),
            )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={
            "workspace": "default",
            "person_slug": "alice",
            "query": "Who is Alice's sister?",
            "actor": _actor(settings),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is False
    assert payload["answerable"] is True
    assert "Maria" in payload["answer"]
    assert "Noah" not in payload["answer"]
    assert "Riley" not in payload["answer"]
    assert payload["retrieval"]["support_level"] == "supported"
    assert len(payload["retrieval"]["hits"]) == 1
    assert payload["retrieval"]["hits"][0]["domain"] == "biography"
    assert payload["retrieval"]["hits"][0]["category"] == "family"


@pytest.mark.parametrize(
    ("query", "domain", "category", "canonical_key", "payload_data", "summary", "quote_text", "expected_support_level", "expected_fragment"),
    [
        (
            "Does Alice live in Berlin?",
            "biography",
            "residence",
            "alice:biography:residence:lisbon",
            {"city": "Lisbon"},
            "Alice lives in Lisbon.",
            "Alice lives in Lisbon.",
            "contradicted",
            "I do not have evidence",
        ),
        (
            "Does Alice prefer coffee?",
            "preferences",
            "preference",
            "alice:preferences:preference:tea",
            {"value": "tea", "polarity": "like", "is_current": True},
            "Alice prefers tea.",
            "Alice prefers tea.",
            "contradicted",
            "I do not have evidence",
        ),
        (
            "Did Alice attend JSConf?",
            "experiences",
            "event",
            "alice:experiences:event:pycon",
            {"event": "PyCon", "temporal_anchor": "2026"},
            "Alice attended PyCon.",
            "Alice attended PyCon in 2026.",
            "contradicted",
            "I do not have evidence",
        ),
        (
            "Did Alice attend PyCon in 2025?",
            "experiences",
            "event",
            "alice:experiences:event:pycon-2026",
            {"event": "PyCon", "temporal_anchor": "2026"},
            "Alice attended PyCon.",
            "Alice attended PyCon in 2026.",
            "contradicted",
            "I do not have evidence",
        ),
        (
            "Is Bob Alice's brother?",
            "social_circle",
            "friend",
            "alice:social_circle:friend:bob",
            {"relation": "friend", "target_label": "Bob"},
            "Alice says Bob is their friend.",
            "Bob is my friend.",
            "contradicted",
            "I do not have evidence",
        ),
    ],
)
def test_chat_refuses_false_premise_claims_across_classes(
    monkeypatch,
    settings,
    query,
    domain,
    category,
    canonical_key,
    payload_data,
    summary,
    quote_text,
    expected_support_level,
    expected_fragment,
):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            parsed_text=quote_text,
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain=domain,
                category=category,
                canonical_key=canonical_key,
                payload=payload_data,
                summary=summary,
                source_kind="explicit",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text=quote_text,
            ),
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": query, "actor": _actor(settings)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["answerable"] is False
    assert payload["must_not_use_as_fact"] is True
    assert expected_fragment in payload["answer"]
    assert payload["retrieval"]["support_level"] == expected_support_level
    assert payload["retrieval"]["refusal_category"] == "contradicted_by_memory"
    assert payload["retrieval"]["unsupported_premise_detected"] is True
    assert len(payload["retrieval"]["hits"]) == 1
    assert payload["agent_response"]["answerable"] is False


def test_chat_ignores_style_and_psychometrics_for_factual_answers(monkeypatch, settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
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
            source_path="var/raw/alice-style.md",
            source_type="note",
            origin_uri="/tmp/alice-style.md",
            title="alice-style",
            sha256="ghi791",
            parsed_text="Haha, I am curious.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="style",
                category="communication_style",
                canonical_key="alice:style:communication_style:humorous",
                payload={"tone": "humorous", "generation_guidance": "Use light humor."},
                summary="Alice often communicates humorously.",
                source_kind="explicit",
                confidence=0.6,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Haha",
            ),
            locator={"message_ids": ["1"]},
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Does Alice own a cat?", "actor": _actor(settings)},
    )

    assert response.status_code == 200
    assert response.json()["refused"] is True

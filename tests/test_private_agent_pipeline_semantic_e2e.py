from __future__ import annotations

from memco.db import get_connection
from memco.models.retrieval import RetrievalRequest
from memco.repositories.fact_repository import FactRepository
from memco.services.answer_service import AnswerService
from memco.services.pipeline_service import IngestPipelineService
from memco.services.retrieval_service import RetrievalService


def _ingest(settings, text: str) -> dict:
    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Tom",
            slug="tom",
            person_type="human",
            aliases=["Tom"],
        )
        return IngestPipelineService().ingest_text(
            settings,
            conn,
            workspace_slug="default",
            text=text,
            source_type="chat",
            title="dense-e2e",
            person_display_name="Alice",
            person_slug="alice",
            aliases=["Alice"],
            conversation_uid="dense-e2e",
        )


def _answer(settings, query: str):
    with get_connection(settings.db_path) as conn:
        retrieval = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query=query, limit=8),
        )
    answer = AnswerService().build_answer(query=query, retrieval_result=retrieval)
    return retrieval, answer


def test_dense_message_extracts_atomic_persona_facts(settings):
    _ingest(
        settings,
        """
        2026-04-01T10:00:00Z Alice: My name is Alice. I live in Lisbon. I currently prefer coffee, but I used to prefer tea. My sister is Maria and my best friend is Tom. I attended PyCon in May 2024 with Bob and learned to plan rehearsals. In October 2023, I had a serious car accident during a road trip to the Grand Canyon and I paused hiking for two months. I shipped Project Atlas with Bob on the mobile team; the outcome was 20% faster onboarding. I work as a designer and use Python and Postgres.
        2026-04-01T10:02:00Z Bob: I live in Berlin and I work at Stripe.
        """.strip(),
    )

    checks = [
        ("Where does Alice live?", "Lisbon"),
        ("What does Alice currently prefer?", "coffee"),
        ("What did Alice used to prefer?", "tea"),
        ("Who is Alice's sister?", "Maria"),
        ("Who is Alice's best friend?", "Tom"),
        ("Where did Alice have an accident?", "Grand Canyon"),
        ("When did Alice attend PyCon?", "May 2024"),
        ("Who did Alice attend PyCon with?", "Bob"),
        ("What changed in Alice's life after the accident?", "paused hiking for two months"),
        ("What tools does Alice use?", "Python"),
        ("What tools does Alice use?", "Postgres"),
    ]
    for query, expected in checks:
        retrieval, answer = _answer(settings, query)
        assert expected.lower() in answer["answer"].lower(), (query, answer, retrieval.model_dump(mode="json"))

    retrieval, answer = _answer(settings, "Where does Bob live?")
    assert retrieval.support_level == "unsupported"
    assert retrieval.refusal_category == "subject_mismatch"
    assert answer["must_not_use_as_fact"] is True

from __future__ import annotations

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _actor():
    return {
        "actor_id": "dev-owner",
        "actor_type": "owner",
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": True,
    }


def test_style_and_psychometrics_do_not_answer_factual_questions(monkeypatch, settings):
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
            source_path="var/raw/style-psy.md",
            source_type="note",
            origin_uri="/tmp/style-psy.md",
            title="style-psy",
            sha256="style-psy-sha",
            parsed_text="Haha, I am very curious.",
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
                confidence=0.6,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Haha",
            ),
            locator={"message_ids": ["1"]},
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="psychometrics",
                category="trait",
                subcategory="big_five",
                canonical_key="alice:psychometrics:big_five:openness",
                payload={"framework": "big_five", "trait": "openness", "score": 0.7},
                summary="Alice may score high on openness.",
                confidence=0.55,
                observed_at="2026-04-21T10:01:00Z",
                source_id=source_id,
                quote_text="I am very curious.",
            ),
            locator={"message_ids": ["2"]},
        )

    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)
    response = client.post(
        "/v1/chat",
        json={"workspace": "default", "person_slug": "alice", "query": "Does Alice own a cat?", "actor": _actor()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is True
    assert payload["retrieval"]["hits"] == []

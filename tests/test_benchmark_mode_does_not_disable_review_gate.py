from __future__ import annotations

import json

from memco.db import get_connection
from memco.models.retrieval import RetrievalRequest
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.services.candidate_service import CandidateService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.services.retrieval_service import RetrievalService


def test_benchmark_mode_does_not_disable_review_gate(settings, tmp_path):
    source_path = tmp_path / "ordinary-extraction.json"
    source_path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-28T10:00:00Z",
                        "text": "I moved to Lisbon.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    candidate_repo = CandidateRepository()
    fact_repo = FactRepository()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source_path,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        candidates = CandidateService(
            extraction_service=ExtractionService.from_settings(settings),
            candidate_repository=candidate_repo,
        ).extract_from_conversation(
            conn,
            workspace_slug="default",
            conversation_id=conversation.conversation_id,
        )
        facts = fact_repo.list_facts(conn, workspace_slug="default", person_id=int(person["id"]), status="active")
        retrieval = RetrievalService().retrieve(
            conn,
            RetrievalRequest(workspace="default", person_slug="alice", query="Where does Alice live?", limit=5),
        )

    assert candidates
    assert {candidate["candidate_status"] for candidate in candidates} <= {"validated_candidate", "needs_review"}
    assert all(candidate["candidate_status"] != "published" for candidate in candidates)
    assert facts == []
    assert retrieval.hits == []
    assert retrieval.answerable is False
    assert retrieval.support_level != "supported"

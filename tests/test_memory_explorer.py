from __future__ import annotations

import json

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.review_repository import ReviewRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def test_memory_explorer_snapshot_surfaces_facts_evidence_reviews_changes_and_hints(settings):
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    candidate_repo = CandidateRepository()
    review_repo = ReviewRepository()
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
            source_path="var/raw/memory-explorer.md",
            source_type="note",
            origin_uri="/tmp/memory-explorer.md",
            title="memory-explorer",
            sha256="memory-explorer-sha",
            parsed_text="Alice lives in Lisbon. Bob is my friend.",
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text="Alice lives in Lisbon. Bob is my friend.")
        chunk_id = int(
            conn.execute(
                "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
                (source_id,),
            ).fetchone()["id"]
        )
        source_segment_id = int(source_repo.get_segment_by_chunk_id(conn, chunk_id=chunk_id)["id"])
        fact = consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="alice:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Alice lives in Lisbon.",
                confidence=0.9,
                observed_at="2026-04-21T10:00:00Z",
                source_id=source_id,
                quote_text="Alice lives in Lisbon.",
            ),
            source_chunk_id=chunk_id,
            source_segment_id=source_segment_id,
        )
        consolidation.mark_deleted(conn, fact_id=int(fact["id"]), reason="explorer rollback target")
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="conversation",
            chunk_id=chunk_id,
            domain="social_circle",
            category="friend",
            subcategory="",
            canonical_key="alice:social_circle:friend:bob",
            payload={"relation": "friend", "target_label": "Bob", "target_person_id": None},
            summary="Alice says Bob is their friend.",
            confidence=0.55,
            reason="relation_target_unresolved",
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=[
                {
                    "quote": "Bob is my friend.",
                    "message_ids": [],
                    "source_segment_ids": [source_segment_id],
                    "chunk_kind": "conversation",
                }
            ],
        )
        candidate = candidate_repo.mark_candidate_status(
            conn,
            candidate_id=int(candidate["id"]),
            candidate_status="needs_review",
            reason="relation_target_unresolved",
        )
        review_repo.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )

    runner = CliRunner()
    command = get_command(app)
    result = runner.invoke(
        command,
        [
            "memory-explorer",
            "--root",
            str(settings.root),
            "--person-slug",
            "alice",
            "--domain",
            "biography",
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "memory_explorer_snapshot"
    assert payload["filters"]["domain"] == "biography"
    assert payload["counts"]["facts"] == 1
    assert payload["facts"][0]["summary"] == "Alice lives in Lisbon."
    assert payload["facts"][0]["evidence"][0]["quote_text"] == "Alice lives in Lisbon."
    assert payload["changes"][0]["operation_type"] == "deleted"
    assert payload["changes"][0]["target_fact_id"] == fact["id"]
    assert payload["review"]["filters"]["domain"] == "biography"
    assert payload["review"]["summary"]["review_item_count"] == 0
    assert payload["review"]["candidate_cards"] == []
    assert "review-resolve approved" in payload["action_hints"]["approve_review"]
    assert "candidate-reject" in payload["action_hints"]["reject_candidate"]
    assert "fact-rollback" in payload["action_hints"]["rollback_change"]

    social_result = runner.invoke(
        command,
        [
            "memory-explorer",
            "--root",
            str(settings.root),
            "--person-slug",
            "alice",
            "--domain",
            "social_circle",
        ],
        prog_name="memco",
    )

    assert social_result.exit_code == 0, social_result.output
    social_payload = json.loads(social_result.output)
    assert social_payload["filters"]["domain"] == "social_circle"
    assert social_payload["counts"]["facts"] == 0
    assert social_payload["changes"] == []
    assert social_payload["review"]["filters"]["domain"] == "social_circle"
    assert social_payload["review"]["summary"]["review_item_count"] == 1
    assert social_payload["review"]["candidate_cards"][0]["evidence_preview"][0]["quote"] == "Bob is my friend."


def test_memory_explorer_help_points_to_core_operator_actions():
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(command, ["memory-explorer", "--help"], prog_name="memco")

    assert result.exit_code == 0, result.output
    assert "facts with evidence" in result.output
    assert "review candidates" in result.output
    assert "rollback hints" in result.output
    assert "--domain" in result.output

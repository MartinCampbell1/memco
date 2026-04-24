from __future__ import annotations

import json
import re

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app
from memco.repositories.candidate_repository import CandidateRepository
from memco.db import get_connection
from memco.repositories.fact_repository import FactRepository
from memco.repositories.review_repository import ReviewRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.ingest_service import IngestService


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def test_cli_init_and_person_upsert(settings):
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(
        command,
        ["init-db", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    assert "Storage contract: postgres-primary" in result.output
    assert "Storage role: fallback" in result.output
    assert "Storage engine: sqlite" in result.output
    assert f"Database ready at {settings.db_path}" in result.output

    result = runner.invoke(
        command,
        ["person-upsert", "CLI Alice", "--root", str(settings.root), "--alias", "Alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["display_name"] == "CLI Alice"


def test_cli_local_artifacts_refresh_command(monkeypatch, settings):
    runner = CliRunner()
    command = get_command(app)

    monkeypatch.setattr(
        "memco.cli.main._project_root",
        lambda project_root: settings.root.resolve(),
    )
    monkeypatch.setattr(
        "memco.cli.main.refresh_local_artifacts",
        lambda **kwargs: {
            "artifact_type": "local_artifact_refresh",
            "project_root": str(kwargs["project_root"]),
            "artifacts": {"repo_local_status": "/tmp/status.json"},
            "summaries": {"full_suite": "262 passed in 5.00s"},
        },
    )

    result = runner.invoke(
        command,
        ["local-artifacts-refresh", "--project-root", str(settings.root)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "local_artifact_refresh"
    assert payload["project_root"] == str(settings.root.resolve())


def test_cli_local_artifacts_refresh_command_supports_postgres_and_output(monkeypatch, settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    output_path = tmp_path / "artifacts" / "local-artifacts-refresh.json"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "memco.cli.main._project_root",
        lambda project_root: settings.root.resolve(),
    )

    def fake_refresh_local_artifacts(**kwargs):
        captured.update(kwargs)
        return {
            "artifact_type": "local_artifact_refresh",
            "project_root": str(kwargs["project_root"]),
            "artifacts": {
                "release_check": "/tmp/release-check-current.json",
                "release_check_postgres": "/tmp/release-check-postgres-current.json",
            },
            "summaries": {
                "full_suite": "264 passed in 5.91s",
                "contract_stack": "46 passed in 0.76s",
            },
        }

    monkeypatch.setattr("memco.cli.main.refresh_local_artifacts", fake_refresh_local_artifacts)

    result = runner.invoke(
        command,
        [
            "local-artifacts-refresh",
            "--project-root",
            str(settings.root),
            "--postgres-database-url",
            "postgresql://example/postgres",
            "--output",
            str(output_path),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert captured["project_root"] == settings.root.resolve()
    assert captured["postgres_database_url"] == "postgresql://example/postgres"
    assert payload["artifact_path"] == str(output_path.resolve())
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == payload


def test_cli_local_artifacts_refresh_command_returns_nonzero_on_failure(monkeypatch, settings):
    runner = CliRunner()
    command = get_command(app)

    monkeypatch.setattr(
        "memco.cli.main._project_root",
        lambda project_root: settings.root.resolve(),
    )
    monkeypatch.setattr(
        "memco.cli.main.refresh_local_artifacts",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("local artifact refresh failed")),
    )

    result = runner.invoke(
        command,
        ["local-artifacts-refresh", "--project-root", str(settings.root)],
        prog_name="memco",
    )

    assert result.exit_code == 1
    assert "local artifact refresh failed" in result.output


def test_cli_ingest_pipeline_happy_path(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    source = tmp_path / "pipeline-happy.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        command,
        [
            "ingest-pipeline",
            str(source),
            "--root",
            str(settings.root),
            "--person-display-name",
            "Alice",
            "--person-slug",
            "alice",
            "--alias",
            "Alice",
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["person"]["slug"] == "alice"
    assert payload["conversation"]["conversation_id"] >= 1
    assert payload["extracted_total"] == 1
    assert payload["validated_candidate_ids"] != []
    assert len(payload["published"]) == 1
    assert payload["published"][0]["fact"]["payload"]["city"] == "Lisbon"
    assert payload["pending_review_items"] == []


def test_cli_ingest_pipeline_reports_pending_review_items(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    source = tmp_path / "pipeline-review.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Guest", "timestamp": "2026-04-21T10:00:00Z", "text": "Bob is my friend."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        command,
        ["ingest-pipeline", str(source), "--root", str(settings.root)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["person"] is None
    assert payload["conversation"]["unresolved_speakers"] != []
    assert payload["published"] == []
    assert payload["pending_review_items"] != []


def test_cli_candidate_extract_and_list(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    source = tmp_path / "cli-conversation.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
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
            path=source,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )

    result = runner.invoke(
        command,
        ["candidate-extract", str(conversation.conversation_id), "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    items = json.loads(result.output)
    assert any(item["domain"] == "biography" for item in items)

    result = runner.invoke(
        command,
        ["candidate-list", "--root", str(settings.root), "--candidate-status", "validated_candidate"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    listed = json.loads(result.output)
    assert any(item["domain"] == "biography" for item in listed)


def test_cli_fact_list_delete_restore(settings):
    runner = CliRunner()
    command = get_command(app)
    source_repo = SourceRepository()

    result = runner.invoke(
        command,
        ["person-upsert", "CLI Bob", "--root", str(settings.root), "--alias", "Bob"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    person = json.loads(result.output)

    with get_connection(settings.db_path) as conn:
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/cli-bob.md",
            source_type="note",
            origin_uri="/tmp/cli-bob.md",
            title="cli-bob",
            sha256="cli-bob-sha",
            parsed_text="CLI Bob lives in Berlin.",
        )

    result = runner.invoke(
        command,
        [
            "fact-add",
            "cli-bob",
            "biography",
            "residence",
            "cli-bob:biography:residence:berlin",
            "2026-04-21T10:00:00Z",
            str(source_id),
            "--root",
            str(settings.root),
            "--payload-json",
            '{"city":"Berlin"}',
            "--summary",
            "CLI Bob lives in Berlin.",
            "--quote-text",
            "CLI Bob lives in Berlin.",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    fact = json.loads(result.output)

    result = runner.invoke(
        command,
        ["fact-list", "--root", str(settings.root), "--person-id", str(person["id"])],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    listed = json.loads(result.output)
    assert any(item["id"] == fact["id"] for item in listed)

    result = runner.invoke(
        command,
        ["fact-delete", str(fact["id"]), "--root", str(settings.root), "--reason", "cleanup"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    deleted = json.loads(result.output)
    assert deleted["status"] == "deleted"

    result = runner.invoke(
        command,
        ["fact-restore", str(fact["id"]), "--root", str(settings.root), "--reason", "restore"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    restored = json.loads(result.output)
    assert restored["status"] == "active"

    result = runner.invoke(
        command,
        ["fact-operations", "--root", str(settings.root), "--target-fact-id", str(fact["id"])],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    operations = json.loads(result.output)
    assert any(item["operation_type"] == "deleted" for item in operations)

    delete_operation = next(item for item in operations if item["operation_type"] == "deleted")
    result = runner.invoke(
        command,
        ["fact-rollback", str(delete_operation["id"]), "--root", str(settings.root), "--reason", "undo delete"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    rolled_back = json.loads(result.output)
    assert rolled_back["status"] == "active"


def test_cli_conversation_speaker_resolution(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    source = tmp_path / "cli-speaker.json"
    source.write_text(
        json.dumps(
            {"messages": [{"speaker": "Guest", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Guest User",
            slug="guest-user",
            person_type="human",
            aliases=["Guest User"],
        )
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )

    result = runner.invoke(
        command,
        ["conversation-speakers", str(conversation.conversation_id), "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    speakers = json.loads(result.output)
    assert speakers[0]["person_id"] is None

    result = runner.invoke(
        command,
        [
            "conversation-speaker-resolve",
            "guest",
            "--latest-conversation",
            "--root",
            str(settings.root),
            "--person-slug",
            "guest-user",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mapping"]["person_id"] is not None
    assert any(item["domain"] == "biography" for item in payload["candidates"])


def test_cli_person_alias_and_merge(settings):
    runner = CliRunner()
    command = get_command(app)
    source_repo = SourceRepository()

    result = runner.invoke(
        command,
        ["person-upsert", "Alice", "--root", str(settings.root), "--alias", "Alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    alice = json.loads(result.output)

    result = runner.invoke(
        command,
        ["person-upsert", "Maria", "--root", str(settings.root), "--alias", "Maria"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    maria = json.loads(result.output)

    result = runner.invoke(
        command,
        ["person-alias-upsert", "A. Example", "--root", str(settings.root), "--person-slug", "alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    alias = json.loads(result.output)
    assert alias["normalized_alias"] == "a. example"

    with get_connection(settings.db_path) as conn:
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/cli-person-merge.md",
            source_type="note",
            origin_uri="/tmp/cli-person-merge.md",
            title="cli-person-merge",
            sha256="cli-person-merge-sha",
            parsed_text="Maria lives in Lisbon.",
        )

    result = runner.invoke(
        command,
        [
            "fact-add",
            "maria",
            "biography",
            "residence",
            "maria:biography:residence:lisbon",
            "2026-04-21T10:00:00Z",
            str(source_id),
            "--root",
            str(settings.root),
            "--payload-json",
            '{"city":"Lisbon"}',
            "--summary",
            "Maria lives in Lisbon.",
            "--quote-text",
            "Maria lives in Lisbon.",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["person-merge", "--root", str(settings.root), "--from-person-slug", "maria", "--to-person-slug", "alice", "--reason", "same person"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    merge = json.loads(result.output)
    assert merge["from_person_id"] == maria["id"]
    assert merge["to_person_id"] == alice["id"]


def test_cli_operator_flow_supports_supersede_rollback(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)

    def invoke_json(args: list[str]) -> dict | list[dict]:
        result = runner.invoke(command, args, prog_name="memco")
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    first_source = tmp_path / "operator-flow-1.json"
    first_source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T09:00:00Z", "text": "I live in Berlin."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second_source = tmp_path / "operator-flow-2.json"
    second_source.write_text(
        json.dumps(
            {
                "messages": [
                    {"speaker": "Alice", "timestamp": "2026-04-21T12:00:00Z", "text": "I moved to Lisbon."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    init_result = runner.invoke(
        command,
        ["init-db", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert init_result.exit_code == 0, init_result.output

    person = invoke_json(
        ["person-upsert", "Alice", "--root", str(settings.root), "--slug", "alice", "--alias", "Alice"]
    )
    imported_first = invoke_json(
        ["import", str(first_source), "--root", str(settings.root), "--source-type", "json"]
    )
    imported_second = invoke_json(
        ["import", str(second_source), "--root", str(settings.root), "--source-type", "json"]
    )

    first_conversation = invoke_json(
        [
            "conversation-import",
            str(imported_first["source_id"]),
            "--root",
            str(settings.root),
            "--conversation-uid",
            "operator-flow-1",
            "--title",
            "Operator Flow 1",
        ]
    )
    second_conversation = invoke_json(
        [
            "conversation-import",
            str(imported_second["source_id"]),
            "--root",
            str(settings.root),
            "--conversation-uid",
            "operator-flow-2",
            "--title",
            "Operator Flow 2",
        ]
    )

    first_candidates = invoke_json(
        [
            "candidate-extract",
            str(first_conversation["conversation_id"]),
            "--root",
            str(settings.root),
        ]
    )
    first_biography = next(item for item in first_candidates if item["domain"] == "biography")
    first_publish = invoke_json(
        ["candidate-publish", str(first_biography["id"]), "--root", str(settings.root)]
    )
    assert first_publish["fact"]["payload"]["city"] == "Berlin"

    second_candidates = invoke_json(
        [
            "candidate-extract",
            str(second_conversation["conversation_id"]),
            "--root",
            str(settings.root),
        ]
    )
    second_biography = next(item for item in second_candidates if item["domain"] == "biography")
    second_publish = invoke_json(
        ["candidate-publish", str(second_biography["id"]), "--root", str(settings.root)]
    )
    assert second_publish["fact"]["payload"]["city"] == "Lisbon"

    retrieved_current = invoke_json(
        ["retrieve", "Where does Alice live?", "alice", "--root", str(settings.root)]
    )
    assert [item["payload"]["city"] for item in retrieved_current["hits"]] == ["Lisbon"]

    supported_chat = invoke_json(
        ["chat", "Where does Alice live?", "alice", "--root", str(settings.root)]
    )
    assert supported_chat["refused"] is False
    assert "Lisbon" in supported_chat["answer"]
    assert len(supported_chat["fact_ids"]) == 1
    assert len(supported_chat["evidence_ids"]) == 1

    false_premise_chat = invoke_json(
        ["chat", "Does Alice work at Stripe?", "alice", "--root", str(settings.root)]
    )
    assert false_premise_chat["refused"] is True
    assert false_premise_chat["answerable"] is False
    assert false_premise_chat["must_not_use_as_fact"] is True
    assert false_premise_chat["answer"] == "I don't have confirmed memory evidence for that."

    core_only_retrieve = invoke_json(
        ["retrieve", "Where does Alice live?", "alice", "--detail-policy", "core_only", "--root", str(settings.root)]
    )
    assert core_only_retrieve["detail_policy"] == "core_only"
    assert core_only_retrieve["hits"][0]["summary"] == "Alice lives in Lisbon."
    assert "payload" not in core_only_retrieve["hits"][0]

    facts_before_rollback = invoke_json(
        [
            "fact-list",
            "--root",
            str(settings.root),
            "--person-id",
            str(person["id"]),
            "--domain",
            "biography",
        ]
    )
    statuses_before = {item["summary"]: item["status"] for item in facts_before_rollback}
    assert statuses_before["Alice lives in Lisbon."] == "active"
    assert statuses_before["Alice lives in Berlin."] == "superseded"
    superseded_fact = next(item for item in facts_before_rollback if item["summary"] == "Alice lives in Berlin.")

    supersede_operations = invoke_json(
        [
            "fact-operations",
            "--root",
            str(settings.root),
            "--target-fact-id",
            str(superseded_fact["id"]),
            "--operation-type",
            "superseded",
        ]
    )
    supersede_operation = supersede_operations[0]

    rolled_back = invoke_json(
        [
            "fact-rollback",
            str(supersede_operation["id"]),
            "--root",
            str(settings.root),
            "--reason",
            "undo operator flow supersede",
        ]
    )
    assert rolled_back["status"] == "active"
    assert rolled_back["payload"]["city"] == "Berlin"

    active_facts_after = invoke_json(
        [
            "fact-list",
            "--root",
            str(settings.root),
            "--person-id",
            str(person["id"]),
            "--domain",
            "biography",
            "--status",
            "active",
        ]
    )
    assert [item["summary"] for item in active_facts_after] == ["Alice lives in Berlin."]

    facts_after_rollback = invoke_json(
        [
            "fact-list",
            "--root",
            str(settings.root),
            "--person-id",
            str(person["id"]),
            "--domain",
            "biography",
        ]
    )
    statuses_after = {item["summary"]: item["status"] for item in facts_after_rollback}
    assert statuses_after["Alice lives in Berlin."] == "active"
    assert statuses_after["Alice lives in Lisbon."] != "active"
    assert statuses_after["Alice lives in Lisbon."] == "deleted"

    retrieved_after_rollback = invoke_json(
        ["retrieve", "Where does Alice live?", "alice", "--root", str(settings.root)]
    )
    assert [item["payload"]["city"] for item in retrieved_after_rollback["hits"]] == ["Berlin"]


def test_cli_flow_commands_advertise_next_steps(settings):
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(command, ["import", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    import_help = _plain(result.output)
    assert "conversation-import SOURCE_ID" in import_help

    result = runner.invoke(command, ["conversation-import", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    conversation_help = _plain(result.output)
    assert "candidate-extract" in conversation_help
    assert "CONVERSATION_ID" in conversation_help
    assert "--latest-source" in conversation_help

    result = runner.invoke(command, ["candidate-extract", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    extract_help = _plain(result.output)
    assert "candidate-publish" in extract_help
    assert "review-list" in extract_help
    assert "--latest-conversation" in extract_help

    result = runner.invoke(command, ["candidate-publish", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    publish_help = _plain(result.output)
    assert "retrieve" in publish_help
    assert "fact-operations" in publish_help
    assert "--latest-candidate" in publish_help
    assert "--person-slug" in publish_help
    assert "--domain" in publish_help

    result = runner.invoke(command, ["candidate-reject", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    reject_help = _plain(result.output)
    assert "--latest-candidate" in reject_help
    assert "--person-slug" in reject_help
    assert "--domain" in reject_help

    result = runner.invoke(command, ["fact-rollback", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    rollback_help = _plain(result.output)
    assert "fact-list" in rollback_help
    assert "retrieve" in rollback_help
    assert "--latest-operation" in rollback_help

    result = runner.invoke(command, ["conversation-speakers", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    speakers_help = _plain(result.output)
    assert "conversation-speaker-resolve" in speakers_help
    assert "candidate-extract" in speakers_help
    assert "--latest-conversation" in speakers_help

    result = runner.invoke(command, ["conversation-speaker-resolve", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    speaker_resolve_help = _plain(result.output)
    assert "candidate-extract" in speaker_resolve_help
    assert "CONVERSATION_ID" in speaker_resolve_help
    assert "--latest-conversation" in speaker_resolve_help

    result = runner.invoke(command, ["candidate-list", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    candidate_list_help = _plain(result.output)
    assert "candidate-publish" in candidate_list_help
    assert "review-resolve" in candidate_list_help
    assert "--person-slug" in candidate_list_help

    result = runner.invoke(command, ["review-list", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    review_list_help = _plain(result.output)
    assert "review-resolve" in review_list_help
    assert "candidate-list" in review_list_help
    assert "--person-slug" in review_list_help

    result = runner.invoke(command, ["fact-list", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    fact_list_help = _plain(result.output)
    assert "candidate-publish" in fact_list_help
    assert "fact-rollback" in fact_list_help
    assert "--person-slug" in fact_list_help

    result = runner.invoke(command, ["fact-operations", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    fact_ops_help = _plain(result.output)
    assert "fact-rollback" in fact_ops_help
    assert "--latest-target-fact" in fact_ops_help
    assert "--person-slug" in fact_ops_help

    result = runner.invoke(command, ["fact-delete", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    fact_delete_help = _plain(result.output)
    assert "fact-restore" in fact_delete_help
    assert "retrieve" in fact_delete_help
    assert "--latest-fact" in fact_delete_help
    assert "--person-slug" in fact_delete_help

    result = runner.invoke(command, ["fact-restore", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    fact_restore_help = _plain(result.output)
    assert "fact-list" in fact_restore_help
    assert "retrieve" in fact_restore_help
    assert "--latest-fact" in fact_restore_help
    assert "--person-slug" in fact_restore_help

    result = runner.invoke(command, ["person-list", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    person_list_help = _plain(result.output)
    assert "person-alias-upsert" in person_list_help
    assert "person-merge" in person_list_help

    result = runner.invoke(command, ["person-alias-upsert", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    alias_help = _plain(result.output)
    assert "conversation-speaker-resolve" in alias_help
    assert "candidate-extract" in alias_help

    result = runner.invoke(command, ["person-merge", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    merge_help = _plain(result.output)
    assert "person-list" in merge_help
    assert "retrieve" in merge_help

    result = runner.invoke(command, ["fact-add", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    fact_add_help = _plain(result.output)
    assert "retrieve" in fact_add_help
    assert "fact-operations" in fact_add_help
    assert "--latest-source" in fact_add_help

    result = runner.invoke(command, ["retrieval-log-list", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    retrieval_log_help = _plain(result.output)
    assert "retrieve" in retrieval_log_help
    assert "chat" in retrieval_log_help
    assert "--person-slug" in retrieval_log_help

    result = runner.invoke(command, ["eval-run", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    eval_help = _plain(result.output)
    assert "release-check" in eval_help

    result = runner.invoke(command, ["review-resolve", "--help"], prog_name="memco")
    assert result.exit_code == 0, result.output
    review_resolve_help = _plain(result.output)
    assert "--latest-review" in review_resolve_help
    assert "Resolved person slug" in review_resolve_help
    assert "Resolved target" in review_resolve_help
    assert "--publish" in review_resolve_help
    assert "--person-slug" in review_resolve_help


def test_cli_operator_flow_supports_latest_shortcuts(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    source = tmp_path / "latest-flow.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T10:00:00Z",
                        "text": "I moved to Lisbon.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        command,
        ["person-upsert", "Alice", "--slug", "alice", "--alias", "Alice", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["import", str(source), "--source-type", "json", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["conversation-import", "--latest-source", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    conversation = json.loads(result.output)
    assert conversation["conversation_id"] >= 1

    result = runner.invoke(
        command,
        ["candidate-extract", "--latest-conversation", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    extracted = json.loads(result.output)
    assert len(extracted) == 1

    result = runner.invoke(
        command,
        ["candidate-publish", "--latest-candidate", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    published = json.loads(result.output)
    assert published["candidate"]["candidate_status"] == "published"
    assert published["fact"]["status"] == "active"
    assert published["fact"]["payload"]["city"] == "Lisbon"

    result = runner.invoke(
        command,
        ["retrieve", "Where does Alice live?", "alice", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    retrieval = json.loads(result.output)
    assert [item["payload"]["city"] for item in retrieval["hits"]] == ["Lisbon"]


def test_cli_latest_candidate_publish_fails_closed_on_newer_non_publishable_candidate(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    source = tmp_path / "latest-publish-fail.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T10:00:00Z",
                        "text": "I moved to Lisbon.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        command,
        ["person-upsert", "Alice", "--slug", "alice", "--alias", "Alice", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["import", str(source), "--source-type", "json", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["conversation-import", "--latest-source", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["candidate-extract", "--latest-conversation", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    extracted = json.loads(result.output)
    latest_candidate_id = extracted[0]["id"]

    with get_connection(settings.db_path) as conn:
        conn.execute(
            "UPDATE fact_candidates SET candidate_status = 'needs_review' WHERE id = ?",
            (int(latest_candidate_id),),
        )

    result = runner.invoke(
        command,
        ["candidate-publish", "--latest-candidate", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code != 0
    assert "Cannot publish candidate with status needs_review" in result.output


def test_cli_latest_candidate_publish_can_be_scoped_by_person_slug(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    alice_source = tmp_path / "alice-latest-scope.json"
    bob_source = tmp_path / "bob-latest-scope.json"
    alice_source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T10:00:00Z",
                        "text": "I moved to Lisbon.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bob_source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Bob",
                        "timestamp": "2026-04-21T11:00:00Z",
                        "text": "I moved to Porto.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for display_name, slug in (("Alice", "alice"), ("Bob", "bob")):
        result = runner.invoke(
            command,
            ["person-upsert", display_name, "--slug", slug, "--alias", display_name, "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output

    for source_path in (alice_source, bob_source):
        result = runner.invoke(
            command,
            ["import", str(source_path), "--source-type", "json", "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            command,
            ["conversation-import", "--latest-source", "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            command,
            ["candidate-extract", "--latest-conversation", "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["candidate-publish", "--latest-candidate", "--person-slug", "alice", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    published = json.loads(result.output)
    assert published["fact"]["payload"]["city"] == "Lisbon"

    result = runner.invoke(
        command,
        ["retrieve", "Where does Alice live?", "alice", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    retrieval = json.loads(result.output)
    assert [item["payload"]["city"] for item in retrieval["hits"]] == ["Lisbon"]


def test_cli_latest_candidate_reject_can_be_scoped_by_person_slug(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)
    alice_source = tmp_path / "alice-latest-reject.json"
    bob_source = tmp_path / "bob-latest-reject.json"
    alice_source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Alice",
                        "timestamp": "2026-04-21T10:00:00Z",
                        "text": "I moved to Lisbon.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bob_source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Bob",
                        "timestamp": "2026-04-21T11:00:00Z",
                        "text": "I moved to Porto.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for display_name, slug in (("Alice", "alice"), ("Bob", "bob")):
        result = runner.invoke(
            command,
            ["person-upsert", display_name, "--slug", slug, "--alias", display_name, "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output

    for source_path in (alice_source, bob_source):
        result = runner.invoke(
            command,
            ["import", str(source_path), "--source-type", "json", "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            command,
            ["conversation-import", "--latest-source", "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            command,
            ["candidate-extract", "--latest-conversation", "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        [
            "candidate-reject",
            "--latest-candidate",
            "--person-slug",
            "alice",
            "--root",
            str(settings.root),
            "--reason",
            "reject alice only",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    rejected = json.loads(result.output)
    assert rejected["candidate_status"] == "rejected"
    assert rejected["canonical_key"] == "alice-eval:biography:residence:lisbon" or rejected["payload"]["city"] == "Lisbon"

    result = runner.invoke(
        command,
        ["candidate-list", "--root", str(settings.root), "--person-slug", "alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    alice_candidates = json.loads(result.output)
    assert alice_candidates[0]["candidate_status"] == "rejected"

    result = runner.invoke(
        command,
        ["candidate-list", "--root", str(settings.root), "--person-slug", "bob"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    bob_candidates = json.loads(result.output)
    assert bob_candidates[0]["candidate_status"] != "rejected"


def test_cli_fact_lifecycle_supports_latest_shortcuts(settings):
    runner = CliRunner()
    command = get_command(app)
    source_repo = SourceRepository()

    result = runner.invoke(
        command,
        ["person-upsert", "CLI Bob", "--root", str(settings.root), "--slug", "cli-bob", "--alias", "Bob"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    person = json.loads(result.output)

    with get_connection(settings.db_path) as conn:
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/cli-bob-latest.md",
            source_type="note",
            origin_uri="/tmp/cli-bob-latest.md",
            title="cli-bob-latest",
            sha256="cli-bob-latest-sha",
            parsed_text="CLI Bob lives in Berlin.",
        )

    result = runner.invoke(
        command,
        [
            "fact-add",
            "cli-bob",
            "biography",
            "residence",
            "cli-bob:biography:residence:berlin",
            "2026-04-21T10:00:00Z",
            str(source_id),
            "--root",
            str(settings.root),
            "--payload-json",
            '{"city":"Berlin"}',
            "--summary",
            "CLI Bob lives in Berlin.",
            "--quote-text",
            "CLI Bob lives in Berlin.",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        [
            "fact-delete",
            "--latest-fact",
            "--root",
            str(settings.root),
            "--person-slug",
            "cli-bob",
            "--domain",
            "biography",
            "--reason",
            "cleanup",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    deleted = json.loads(result.output)
    assert deleted["status"] == "deleted"

    result = runner.invoke(
        command,
        [
            "fact-operations",
            "--latest-target-fact",
            "--root",
            str(settings.root),
            "--person-slug",
            "cli-bob",
            "--operation-type",
            "deleted",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    operations = json.loads(result.output)
    assert operations[0]["operation_type"] == "deleted"

    result = runner.invoke(
        command,
        [
            "fact-rollback",
            "--latest-operation",
            "--root",
            str(settings.root),
            "--person-slug",
            "cli-bob",
            "--operation-type",
            "deleted",
            "--reason",
            "undo delete",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    rolled_back = json.loads(result.output)
    assert rolled_back["status"] == "active"


def test_cli_fact_add_supports_latest_source(settings):
    runner = CliRunner()
    command = get_command(app)
    source_repo = SourceRepository()

    result = runner.invoke(
        command,
        ["person-upsert", "CLI Dana", "--root", str(settings.root), "--slug", "cli-dana", "--alias", "Dana"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    person = json.loads(result.output)

    with get_connection(settings.db_path) as conn:
        source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/cli-dana.md",
            source_type="note",
            origin_uri="/tmp/cli-dana.md",
            title="cli-dana",
            sha256="cli-dana-sha",
            parsed_text="CLI Dana lives in Madrid.",
        )

    result = runner.invoke(
        command,
        [
            "fact-add",
            "cli-dana",
            "biography",
            "residence",
            "cli-dana:biography:residence:madrid",
            "2026-04-21T10:00:00Z",
            "--latest-source",
            "--root",
            str(settings.root),
            "--payload-json",
            '{"city":"Madrid"}',
            "--summary",
            "CLI Dana lives in Madrid.",
            "--quote-text",
            "CLI Dana lives in Madrid.",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    fact = json.loads(result.output)
    assert fact["payload"]["city"] == "Madrid"

    result = runner.invoke(
        command,
        ["fact-list", "--root", str(settings.root), "--person-id", str(person["id"])],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    listed = json.loads(result.output)
    assert any(item["id"] == fact["id"] for item in listed)


def test_cli_latest_fact_shortcuts_use_newest_record_not_newest_observed_at(settings):
    runner = CliRunner()
    command = get_command(app)
    source_repo = SourceRepository()

    result = runner.invoke(
        command,
        ["person-upsert", "CLI Eve", "--root", str(settings.root), "--slug", "cli-eve", "--alias", "Eve"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    with get_connection(settings.db_path) as conn:
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/cli-eve-latest.md",
            source_type="note",
            origin_uri="/tmp/cli-eve-latest.md",
            title="cli-eve-latest",
            sha256="cli-eve-latest-sha",
            parsed_text="CLI Eve facts.",
        )

    result = runner.invoke(
        command,
        [
            "fact-add",
            "cli-eve",
            "biography",
            "residence",
            "cli-eve:biography:residence:berlin",
            "2026-04-21T10:00:00Z",
            str(source_id),
            "--root",
            str(settings.root),
            "--payload-json",
            '{"city":"Berlin"}',
            "--summary",
            "CLI Eve lives in Berlin.",
            "--quote-text",
            "CLI Eve lives in Berlin.",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        [
            "fact-add",
            "cli-eve",
            "biography",
            "birthplace",
            "cli-eve:biography:birthplace:porto",
            "2010-01-01T10:00:00Z",
            str(source_id),
            "--root",
            str(settings.root),
            "--payload-json",
            '{"city":"Porto"}',
            "--summary",
            "CLI Eve was born in Porto.",
            "--quote-text",
            "CLI Eve was born in Porto.",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        [
            "fact-delete",
            "--latest-fact",
            "--root",
            str(settings.root),
            "--person-slug",
            "cli-eve",
            "--domain",
            "biography",
            "--reason",
            "cleanup newest record",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    deleted = json.loads(result.output)
    assert deleted["summary"] == "CLI Eve was born in Porto."

    result = runner.invoke(
        command,
        [
            "fact-operations",
            "--latest-target-fact",
            "--root",
            str(settings.root),
            "--person-slug",
            "cli-eve",
            "--domain",
            "biography",
            "--operation-type",
            "deleted",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    operations = json.loads(result.output)
    assert operations[0]["target_fact_id"] == deleted["id"]


def test_cli_review_flow_supports_latest_review_and_slug_resolution(settings, tmp_path):
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(
        command,
        ["person-upsert", "Alice", "--slug", "alice", "--alias", "Alice", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["person-upsert", "Bob", "--slug", "bob", "--alias", "Bob", "--root", str(settings.root)],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output

    with get_connection(settings.db_path) as conn:
        fact_repo = FactRepository()
        source_repo = SourceRepository()
        candidate_repo = CandidateRepository()
        review_repo = ReviewRepository()
        alice_id = fact_repo.resolve_person_id(conn, workspace_slug="default", person_slug="alice")
        bob_id = fact_repo.resolve_person_id(conn, workspace_slug="default", person_slug="bob")
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/review-cli-source.md",
            source_type="note",
            origin_uri="/tmp/review-cli-source.md",
            title="review-cli-source",
            sha256="review-cli-source-sha",
            parsed_text="Alice says Bob is my friend.",
        )
        source_repo.replace_chunks(conn, source_id=source_id, parsed_text="Alice says Bob is my friend.")
        chunk_id = int(
            conn.execute(
                "SELECT id FROM source_chunks WHERE source_id = ? ORDER BY chunk_index ASC LIMIT 1",
                (source_id,),
            ).fetchone()["id"]
        )
        source_segment_id = int(source_repo.get_segment_by_chunk_id(conn, chunk_id=chunk_id)["id"])
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=alice_id,
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
            person_id=alice_id,
            candidate=candidate,
            reason="relation_target_unresolved",
            candidate_id=int(candidate["id"]),
        )

    result = runner.invoke(
        command,
        ["candidate-list", "--root", str(settings.root), "--person-slug", "alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    candidates = json.loads(result.output)
    assert len(candidates) >= 1
    assert candidates[0]["candidate_status"] == "needs_review"

    result = runner.invoke(
        command,
        ["review-list", "--root", str(settings.root), "--status", "pending", "--person-slug", "alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    review_items = json.loads(result.output)
    assert len(review_items) >= 1
    assert review_items[0]["status"] == "pending"
    assert "candidate_summary" in review_items[0]
    assert "candidate_reason_codes" in review_items[0]
    assert review_items[0]["next_action_hint"] == "review-resolve approved|rejected"

    result = runner.invoke(
        command,
        [
            "review-resolve",
            "approved",
            "--latest-review",
            "--root",
            str(settings.root),
            "--person-slug",
            "alice",
            "--candidate-person-slug",
            "alice",
            "--candidate-target-person-slug",
            "bob",
            "--publish",
            "--reason",
            "resolved review path",
        ],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    resolved = json.loads(result.output)
    assert resolved["review"]["status"] == "approved"
    assert resolved["review"]["decision_summary"].startswith("approved")
    assert resolved["review"]["candidate"]["candidate_status"] == "published"
    assert resolved["review"]["candidate"]["payload"]["target_person_id"] is not None
    assert resolved["publish"]["fact"]["domain"] == "social_circle"


def test_cli_retrieval_log_list_supports_person_slug(settings):
    runner = CliRunner()
    command = get_command(app)
    source_repo = SourceRepository()

    for display_name, slug, city in (("Alice", "alice", "Lisbon"), ("Bob", "bob", "Porto")):
        result = runner.invoke(
            command,
            ["person-upsert", display_name, "--slug", slug, "--alias", display_name, "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output
        person = json.loads(result.output)
        with get_connection(settings.db_path) as conn:
            source_id = source_repo.record_source(
                conn,
                workspace_slug="default",
                source_path=f"var/raw/{slug}-logs.md",
                source_type="note",
                origin_uri=f"/tmp/{slug}-logs.md",
                title=f"{slug}-logs",
                sha256=f"{slug}-logs-sha",
                parsed_text=f"{display_name} lives in {city}.",
            )
        result = runner.invoke(
            command,
            [
                "fact-add",
                slug,
                "biography",
                "residence",
                f"{slug}:biography:residence:{city.lower()}",
                "2026-04-21T10:00:00Z",
                str(source_id),
                "--root",
                str(settings.root),
                "--payload-json",
                json.dumps({"city": city}),
                "--summary",
                f"{display_name} lives in {city}.",
                "--quote-text",
                f"{display_name} lives in {city}.",
            ],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output

        result = runner.invoke(
            command,
            ["retrieve", f"Where does {display_name} live?", slug, "--root", str(settings.root)],
            prog_name="memco",
        )
        assert result.exit_code == 0, result.output

    result = runner.invoke(
        command,
        ["retrieval-log-list", "--root", str(settings.root), "--person-slug", "alice"],
        prog_name="memco",
    )
    assert result.exit_code == 0, result.output
    logs = json.loads(result.output)
    assert len(logs) == 1
    assert logs[0]["route_name"] == "retrieve"

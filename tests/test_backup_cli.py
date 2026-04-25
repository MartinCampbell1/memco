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


def _seed_backup_persona(settings) -> None:
    fact_repo = FactRepository()
    candidate_repo = CandidateRepository()
    review_repo = ReviewRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Backup Alice",
            slug="backup-alice",
            person_type="human",
            aliases=["Backup Alice"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/backup-alice.md",
            source_type="markdown",
            origin_uri="/tmp/backup-alice.md",
            title="backup-alice",
            sha256="backup-alice-sha",
            parsed_text="Backup Alice lives in Lisbon. raw-private-source-text",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="backup-alice:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Backup Alice lives in Lisbon.",
                confidence=0.95,
                observed_at="2026-04-24T10:00:00Z",
                source_id=source_id,
                quote_text="Backup Alice lives in Lisbon. raw-private-quote-text",
            ),
        )
        candidate = candidate_repo.add_candidate(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            source_id=source_id,
            conversation_id=None,
            chunk_kind="source",
            chunk_id=None,
            domain="biography",
            category="residence",
            subcategory="",
            canonical_key="backup-alice:biography:residence:porto",
            payload={"city": "Porto"},
            summary="Backup Alice might live in Porto.",
            confidence=0.55,
            reason="needs_review",
        )
        candidate = candidate_repo.update_candidate_evidence(
            conn,
            candidate_id=int(candidate["id"]),
            evidence=[
                {
                    "quote": "raw-private-candidate-quote",
                    "quote_text": "raw-private-candidate-evidence",
                    "text": "raw-private-candidate-text",
                    "source_id": source_id,
                }
            ],
        )
        review_repo.enqueue(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            candidate=candidate,
            reason="backup audit review",
            candidate_id=int(candidate["id"]),
        )


def test_backup_audit_export_redacts_raw_text_and_verifies(settings, tmp_path):
    _seed_backup_persona(settings)
    runner = CliRunner()
    command = get_command(app)
    backup_path = tmp_path / "audit-backup.json"

    export_result = runner.invoke(
        command,
        ["backup", "export", "--root", str(settings.root), "--mode", "audit", "--output", str(backup_path)],
        prog_name="memco",
    )
    assert export_result.exit_code == 0, export_result.output
    summary = json.loads(export_result.output)
    assert summary["artifact_type"] == "backup_export_summary"
    assert summary["ok"] is True
    assert summary["mode"] == "audit"
    assert summary["encrypted"] is False

    raw_artifact = backup_path.read_text(encoding="utf-8")
    assert "raw-private-source-text" not in raw_artifact
    assert "raw-private-quote-text" not in raw_artifact
    assert "raw-private-candidate-quote" not in raw_artifact
    assert "raw-private-candidate-evidence" not in raw_artifact
    assert "raw-private-candidate-text" not in raw_artifact
    assert '"redacted": true' in raw_artifact

    verify_result = runner.invoke(
        command,
        ["backup", "verify", str(backup_path)],
        prog_name="memco",
    )
    assert verify_result.exit_code == 0, verify_result.output
    verification = json.loads(verify_result.output)
    assert verification["artifact_type"] == "backup_verify"
    assert verification["ok"] is True
    assert verification["sanitized"] is True
    assert verification["migration_compatibility"]["compatible"] is True


def test_backup_runbook_reports_sqlite_backup_restore_and_integrity_commands(settings):
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(
        command,
        ["backup", "runbook", "--root", str(settings.root)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "backup_restore_runbook"
    assert payload["storage_engine"] == "sqlite"
    assert payload["native_backup"]["kind"] == "sqlite_backup"
    assert ".backup" in payload["native_backup"]["command"]
    assert payload["native_restore"]["kind"] == "sqlite_file_restore"
    assert payload["native_restore"]["command"].startswith("cp ")
    assert payload["corruption_check"]["kind"] == "sqlite_integrity_check"
    assert "PRAGMA integrity_check" in payload["corruption_check"]["command"]
    assert "--mode full --encrypted" in payload["json_exports"]["full_encrypted"]["command"]
    assert "restore-dry-run" in payload["json_exports"]["full_encrypted"]["restore_dry_run"]


def test_backup_runbook_reports_postgres_dump_restore_and_dump_check(settings):
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(
        command,
        ["backup", "runbook", "--root", str(settings.root), "--storage-engine", "postgres"],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["storage_engine"] == "postgres"
    assert payload["native_backup"]["kind"] == "postgres_dump"
    assert "pg_dump" in payload["native_backup"]["command"]
    assert "$MEMCO_POSTGRES_DATABASE_URL" in payload["native_backup"]["command"]
    assert payload["native_restore"]["kind"] == "postgres_restore"
    assert "pg_restore --clean --if-exists" in payload["native_restore"]["command"]
    assert payload["corruption_check"]["kind"] == "postgres_dump_list_check"
    assert "pg_restore --list" in payload["corruption_check"]["command"]


def test_backup_encrypted_full_export_verifies_and_restore_dry_run(settings, tmp_path, monkeypatch):
    _seed_backup_persona(settings)
    monkeypatch.setenv("MEMCO_BACKUP_PASSPHRASE", "correct horse battery staple")
    runner = CliRunner()
    command = get_command(app)
    backup_path = tmp_path / "full-backup.json.enc"

    export_result = runner.invoke(
        command,
        [
            "backup",
            "export",
            "--root",
            str(settings.root),
            "--mode",
            "full",
            "--encrypted",
            "--output",
            str(backup_path),
        ],
        prog_name="memco",
    )
    assert export_result.exit_code == 0, export_result.output
    summary = json.loads(export_result.output)
    assert summary["mode"] == "full"
    assert summary["encrypted"] is True

    raw_artifact = backup_path.read_text(encoding="utf-8")
    assert "raw-private-source-text" not in raw_artifact
    assert "raw-private-quote-text" not in raw_artifact
    assert "raw-private-candidate-quote" not in raw_artifact
    assert "raw-private-candidate-evidence" not in raw_artifact
    assert "memco_backup_export_encrypted" in raw_artifact

    verify_result = runner.invoke(
        command,
        ["backup", "verify", str(backup_path)],
        prog_name="memco",
    )
    assert verify_result.exit_code == 0, verify_result.output
    verification = json.loads(verify_result.output)
    assert verification["ok"] is True
    assert verification["encrypted"] is True
    assert verification["sanitized"] is False

    dry_run_result = runner.invoke(
        command,
        ["backup", "restore-dry-run", str(backup_path)],
        prog_name="memco",
    )
    assert dry_run_result.exit_code == 0, dry_run_result.output
    dry_run = json.loads(dry_run_result.output)
    assert dry_run["artifact_type"] == "backup_restore_dry_run"
    assert dry_run["ok"] is True
    assert dry_run["would_write"] is False
    assert dry_run["restorable"] is True


def test_backup_verify_reports_malformed_json_without_traceback(tmp_path):
    runner = CliRunner()
    command = get_command(app)
    bad_path = tmp_path / "bad-backup.json"
    bad_path.write_text("{not-json", encoding="utf-8")

    result = runner.invoke(
        command,
        ["backup", "verify", str(bad_path)],
        prog_name="memco",
    )

    assert result.exit_code != 0
    assert "Backup file is not valid JSON." in result.output
    assert "Traceback" not in result.output

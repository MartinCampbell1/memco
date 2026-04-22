from __future__ import annotations

import json

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService


def _seed_persona(settings):
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
            source_path="var/raw/cli-export.md",
            source_type="note",
            origin_uri="/tmp/cli-export.md",
            title="cli-export",
            sha256="cli-export-sha",
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
    return int(person["id"])


def test_cli_persona_export_emits_structured_json_without_raw_content(settings):
    _seed_persona(settings)
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(
        command,
        ["persona-export", "--root", str(settings.root), "--person-slug", "alice"],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "persona_export"
    assert payload["person"]["slug"] == "alice"
    assert payload["counts"]["fact_count"] == 1
    dumped = result.output
    assert "parsed_text" not in dumped
    assert "origin_uri" not in dumped
    assert "quote_text" not in dumped


def test_cli_persona_export_supports_domain_filter(settings):
    _seed_persona(settings)
    runner = CliRunner()
    command = get_command(app)

    result = runner.invoke(
        command,
        ["persona-export", "--root", str(settings.root), "--person-slug", "alice", "--domain", "biography"],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload["domains"].keys()) == {"biography"}


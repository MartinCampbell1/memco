from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app
from memco.config import Settings, write_settings


def test_cli_eval_run_bootstraps_empty_root_as_fixture_sqlite(tmp_path):
    command = get_command(app)
    runner = CliRunner()
    runtime_root = tmp_path / "eval-runtime"

    result = runner.invoke(
        command,
        ["eval-run", "--root", str(runtime_root)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "eval_acceptance_artifact"
    assert payload["failed"] == 0
    settings_text = (runtime_root / "var" / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "profile: fixture" in settings_text
    assert "engine: sqlite" in settings_text


def test_cli_eval_run_rejects_existing_live_runtime_root(tmp_path):
    command = get_command(app)
    runner = CliRunner()
    runtime_root = Path(tmp_path / "live-runtime")
    settings = Settings(root=runtime_root)
    settings.storage.engine = "postgres"
    settings.runtime.profile = "repo-local"
    write_settings(settings)

    result = runner.invoke(
        command,
        ["eval-run", "--root", str(runtime_root)],
        prog_name="memco",
    )

    assert result.exit_code != 0
    assert "do not point it at a live repo/runtime root" in result.output

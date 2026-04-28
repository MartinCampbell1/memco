from __future__ import annotations

import json

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app


def test_private_pilot_gate_command_writes_required_report(tmp_path):
    output = tmp_path / "private-pilot-gate.json"
    root = tmp_path / "pilot-root"
    runner = CliRunner()
    result = runner.invoke(
        get_command(app),
        [
            "private-pilot-gate",
            "--project-root",
            ".",
            "--root",
            str(root),
            "--output",
            str(output),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    checks = {check["name"]: check for check in report["checks"]}

    assert report["artifact_type"] == "private_pilot_gate_report"
    assert report["ok"] is True
    assert report["failures"] == []
    assert checks["pytest_green"]["ok"] is True
    assert checks["personal_memory_eval_green"]["ok"] is True
    assert checks["backup_export_verify_ok"]["ok"] is True
    assert checks["api_memory_context_smoke_ok"]["ok"] is True
    assert checks["unsupported_claims_refused"]["ok"] is True
    assert checks["supported_answers_have_evidence"]["ok"] is True
    assert checks["pending_review_not_leaked"]["ok"] is True
    assert checks["no_benchmark_mode_leakage"]["ok"] is True
    assert report["metrics"]["unsupported_claims_answered_as_fact"] == 0
    assert report["metrics"]["supported_answers_missing_evidence"] == 0
    assert report["metrics"]["pending_candidates_returned_as_confirmed"] == 0

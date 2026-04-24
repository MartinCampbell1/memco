from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app
from memco.models.retrieval import RetrievalRequest
from memco.services.eval_service import EvalService
from memco.services.planner_service import PlannerService


GOLDENS_DIR = Path("eval/personal_memory_goldens")


def _load_goldens() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(GOLDENS_DIR.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            cases.extend(json.loads(line) for line in handle if line.strip())
    return cases


def test_personal_memory_goldens_cover_required_groups():
    cases = _load_goldens()
    counts = {
        group: sum(1 for item in cases if item["group"] == group)
        for group in EvalService.PERSONAL_MEMORY_REQUIRED_COUNTS
    }

    assert len(cases) == 380
    assert len({item["id"] for item in cases}) == len(cases)
    assert counts == EvalService.PERSONAL_MEMORY_REQUIRED_COUNTS


def test_personal_memory_planner_does_not_treat_personal_as_son_relation():
    plan = PlannerService().plan(
        RetrievalRequest(
            person_slug="personal-preference-001",
            query="What is Personal Preference 001 preference?",
            domain="preferences",
            category="preference",
        )
    )

    assert all(check.value != "son" for check in plan.claim_checks)


def test_personal_memory_eval_gate_passes_all_cases(settings):
    result = EvalService().run_personal_memory(project_root=settings.root, goldens_dir=GOLDENS_DIR)

    assert result["artifact_type"] == "personal_memory_eval_artifact"
    assert result["release_scope"] == "personal-agent-memory"
    assert result["ok"] is True
    assert result["total"] == 380
    assert result["passed"] == 380
    assert result["failed"] == 0
    assert result["failures"] == []
    assert all(item["ok"] for item in result["policy_checks"].values())
    assert all(item["ok"] for item in result["dataset_count_checks"].values())
    assert result["metrics"]["core_memory_accuracy"] >= 0.95
    assert result["metrics"]["adversarial_robustness"] >= 0.98
    assert result["metrics"]["cross_person_contamination"] == 0
    assert result["metrics"]["unsupported_premise_answered_as_fact"] == 0
    assert result["metrics"]["evidence_missing_on_supported_answers"] == 0
    assert result["metrics"]["speakerless_owner_fallback_accuracy"] >= 0.95


def test_personal_memory_eval_cli_writes_gate_artifact(tmp_path):
    runner = CliRunner()
    command = get_command(app)
    runtime_root = tmp_path / "personal-memory-runtime"
    output_path = tmp_path / "personal-memory-eval-current.json"

    result = runner.invoke(
        command,
        [
            "eval",
            "personal-memory",
            "--root",
            str(runtime_root),
            "--goldens",
            str(GOLDENS_DIR),
            "--output",
            str(output_path),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["artifact_path"] == str(output_path.resolve())
    assert artifact["ok"] is True
    assert artifact["total"] == 380
    assert artifact["failed"] == 0

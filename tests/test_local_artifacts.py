from __future__ import annotations

import json
import subprocess
from pathlib import Path

from memco.local_artifacts import CONTRACT_STATUS_TEST_FILES, refresh_local_artifacts


def test_refresh_local_artifacts_writes_expected_reports(monkeypatch, tmp_path):
    project_root = tmp_path / "memco"
    reports_dir = project_root / "var" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    def fake_run_release_check(*, project_root, include_eval, postgres_database_url=None):
        artifact = {
            "artifact_type": "repo_local_release_check",
            "ok": True,
            "steps": [
                {
                    "name": "pytest_gate",
                    "stdout": "...\n41 passed in 1.00s\n",
                },
                {
                    "name": "acceptance_artifact",
                    "artifact_summary": {"passed": 24, "total": 24},
                },
            ],
        }
        if postgres_database_url:
            artifact["steps"].append({"name": "postgres_smoke", "ok": True})
        return artifact

    def fake_run(command, cwd, capture_output, text, check):
        joined = " ".join(command)
        if "rev-parse --abbrev-ref HEAD" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="main\n", stderr="")
        if "remote get-url origin" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.com/repo.git\n", stderr="")
        if "status --porcelain" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="M  README.md\n?? src/memco/api/routes/export.py\n", stderr="")
        if list(command[:3]) == [str(command[0]), "-m", "pytest"]:
            if tuple(command[4:]) == CONTRACT_STATUS_TEST_FILES:
                return subprocess.CompletedProcess(command, 0, stdout="...\n46 passed in 0.50s\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="...\n262 passed in 5.00s\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("memco.local_artifacts.run_release_check", fake_run_release_check)
    monkeypatch.setattr("memco.local_artifacts.subprocess.run", fake_run)

    result = refresh_local_artifacts(
        project_root=project_root,
        postgres_database_url="postgresql://example/postgres",
    )

    release = json.loads((reports_dir / "release-check-current.json").read_text(encoding="utf-8"))
    release_pg = json.loads((reports_dir / "release-check-postgres-current.json").read_text(encoding="utf-8"))
    status = json.loads((reports_dir / "repo-local-status-current.json").read_text(encoding="utf-8"))
    groups = json.loads((reports_dir / "change-groups-current.json").read_text(encoding="utf-8"))

    assert result["artifact_type"] == "local_artifact_refresh"
    assert result["summaries"]["full_suite"] == "262 passed in 5.00s"
    assert result["summaries"]["contract_stack"] == "46 passed in 0.50s"
    assert result["summaries"]["release_check_pytest_gate"] == "41 passed in 1.00s"
    assert result["summaries"]["release_check_acceptance"] == "24/24"
    assert result["summaries"]["release_check_postgres_pytest_gate"] == "41 passed in 1.00s"
    assert release["artifact_path"].endswith("release-check-current.json")
    assert release_pg["artifact_path"].endswith("release-check-postgres-current.json")
    assert status["validation"]["full_suite"] == "262 passed in 5.00s"
    assert status["validation"]["contract_stack"] == "46 passed in 0.50s"
    assert status["change_groups_artifact"].endswith("change-groups-current.json")
    grouped_paths = {path for items in groups["groups"].values() for path in items}
    assert "README.md" in grouped_paths
    assert "src/memco/api/routes/export.py" in grouped_paths

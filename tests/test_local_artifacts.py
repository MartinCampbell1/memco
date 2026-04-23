from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from memco.local_artifacts import CONTRACT_STATUS_TEST_FILES, refresh_local_artifacts


def test_refresh_local_artifacts_writes_expected_reports(monkeypatch, tmp_path):
    project_root = tmp_path / "memco"
    reports_dir = project_root / "var" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "live-operator-smoke-current.json").write_text(
        json.dumps(
            {
                "artifact_type": "live_operator_smoke",
                "ok": True,
                "steps": [
                    {"name": "ingest_pipeline", "published_total": 10},
                    {"name": "api_queries", "ok": True},
                ],
                "artifact_path": str(reports_dir / "live-operator-smoke-current.json"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def fake_run_release_check(*, project_root, include_eval, postgres_database_url=None):
        artifact = {
            "artifact_type": "canonical_postgres_release_check" if postgres_database_url else "repo_local_release_check",
            "ok": True,
            "gate_type": "canonical-postgres" if postgres_database_url else "quick-repo-local",
            "steps": [
                {
                    "name": "runtime_policy",
                    "ok": True,
                    "provider": "openai-compatible",
                    "runtime_profile": "repo-local",
                },
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

    def fake_run_strict_release_check(*, project_root, postgres_database_url):
        return {
            "artifact_type": "strict_quality_release_check",
            "ok": True,
            "gate_type": "strict-quality",
            "steps": [
                {"name": "runtime_policy", "ok": True},
                {"name": "pytest_gate", "stdout": "...\n41 passed in 1.00s\n"},
                {"name": "acceptance_artifact", "artifact_summary": {"passed": 24, "total": 24}},
                {"name": "postgres_smoke", "ok": True},
                {
                    "name": "benchmark_artifact",
                    "ok": True,
                    "policy_checks": {
                        "core_memory_accuracy": {"value": 1.0},
                        "adversarial_robustness": {"value": 1.0},
                        "person_isolation": {"value": 1.0},
                    },
                    "artifact_summary": {
                        "artifact_type": "eval_benchmark_artifact",
                        "benchmark_metrics": {
                            "core_memory_accuracy": 1.0,
                            "adversarial_robustness": 1.0,
                            "person_isolation": 1.0,
                        },
                    },
                },
            ],
        }

    def fake_run(command, cwd, capture_output, text, check):
        joined = " ".join(command)
        if "rev-parse --abbrev-ref HEAD" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="main\n", stderr="")
        if "remote get-url origin" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.com/repo.git\n", stderr="")
        if "status --porcelain" in joined:
            return subprocess.CompletedProcess(command, 0, stdout=" M README.md\n?? src/memco/api/routes/export.py\n", stderr="")
        if list(command[:3]) == [str(command[0]), "-m", "pytest"]:
            if tuple(command[4:]) == CONTRACT_STATUS_TEST_FILES:
                return subprocess.CompletedProcess(command, 0, stdout="...\n46 passed in 0.50s\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="...\n262 passed in 5.00s\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("memco.local_artifacts.run_release_check", fake_run_release_check)
    monkeypatch.setattr("memco.local_artifacts.run_strict_release_check", fake_run_strict_release_check)
    monkeypatch.setattr("memco.local_artifacts.subprocess.run", fake_run)

    result = refresh_local_artifacts(
        project_root=project_root,
        postgres_database_url="postgresql://example/postgres",
    )

    release = json.loads((reports_dir / "release-check-current.json").read_text(encoding="utf-8"))
    release_pg = json.loads((reports_dir / "release-check-postgres-current.json").read_text(encoding="utf-8"))
    strict_release = json.loads((reports_dir / "strict-release-check-current.json").read_text(encoding="utf-8"))
    benchmark = json.loads((reports_dir / "benchmark-current.json").read_text(encoding="utf-8"))
    status = json.loads((reports_dir / "repo-local-status-current.json").read_text(encoding="utf-8"))
    groups = json.loads((reports_dir / "change-groups-current.json").read_text(encoding="utf-8"))

    assert result["artifact_type"] == "local_artifact_refresh"
    assert result["summaries"]["full_suite"] == "262 passed in 5.00s"
    assert result["summaries"]["contract_stack"] == "46 passed in 0.50s"
    assert result["summaries"]["release_check_gate_type"] == "quick-repo-local"
    assert result["summaries"]["release_check_runtime_policy"] == "openai-compatible:repo-local:true"
    assert result["summaries"]["release_check_pytest_gate"] == "41 passed in 1.00s"
    assert result["summaries"]["release_check_acceptance"] == "24/24"
    assert result["summaries"]["release_check_postgres_gate_type"] == "canonical-postgres"
    assert result["summaries"]["release_check_postgres_pytest_gate"] == "41 passed in 1.00s"
    assert result["summaries"]["strict_release_check_gate_type"] == "strict-quality"
    assert result["summaries"]["benchmark_core_memory_accuracy"] == 1.0
    assert result["summaries"]["live_operator_smoke_ok"] is True
    assert release["artifact_path"].endswith("release-check-current.json")
    assert release_pg["artifact_path"].endswith("release-check-postgres-current.json")
    assert strict_release["artifact_path"].endswith("strict-release-check-current.json")
    assert benchmark["artifact_path"].endswith("benchmark-current.json")
    assert status["validation"]["full_suite"] == "262 passed in 5.00s"
    assert status["validation"]["contract_stack"] == "46 passed in 0.50s"
    assert status["validation"]["release_check"]["gate_type"] == "quick-repo-local"
    assert status["validation"]["release_check_postgres"]["gate_type"] == "canonical-postgres"
    assert status["validation"]["strict_release_check"]["gate_type"] == "strict-quality"
    assert status["validation"]["benchmark"]["core_memory_accuracy"] == 1.0
    assert status["validation"]["live_operator_smoke"]["ok"] is True
    assert status["validation"]["live_operator_smoke"]["published_total"] == 10
    assert status["change_groups_artifact"].endswith("change-groups-current.json")
    grouped_paths = {path for items in groups["groups"].values() for path in items}
    assert "README.md" in grouped_paths
    assert "src/memco/api/routes/export.py" in grouped_paths


def test_refresh_local_artifacts_clears_live_smoke_env(monkeypatch, tmp_path):
    project_root = tmp_path / "memco"
    reports_dir = project_root / "var" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEMCO_RUN_LIVE_SMOKE", "1")

    def fake_run_release_check(*, project_root, include_eval, postgres_database_url=None):
        assert os.environ.get("MEMCO_RUN_LIVE_SMOKE") is None
        artifact = {
            "artifact_type": "canonical_postgres_release_check" if postgres_database_url else "repo_local_release_check",
            "ok": True,
            "gate_type": "canonical-postgres" if postgres_database_url else "quick-repo-local",
            "steps": [
                {"name": "runtime_policy", "ok": True, "provider": "openai-compatible", "runtime_profile": "repo-local"},
                {"name": "storage_contract", "ok": True, "storage_role": "primary"},
                {"name": "operator_safety", "ok": True},
                {"name": "pytest_gate", "stdout": "...\n41 passed in 1.00s\n"},
                {"name": "acceptance_artifact", "artifact_summary": {"passed": 24, "total": 24}},
            ],
        }
        if postgres_database_url:
            artifact["steps"].append({"name": "postgres_smoke", "ok": True})
        return artifact

    def fake_run_strict_release_check(*, project_root, postgres_database_url):
        assert os.environ.get("MEMCO_RUN_LIVE_SMOKE") is None
        return {
            "artifact_type": "strict_quality_release_check",
            "ok": True,
            "gate_type": "strict-quality",
            "steps": [
                {"name": "runtime_policy", "ok": True},
                {"name": "storage_contract", "ok": True},
                {"name": "operator_safety", "ok": True},
                {"name": "pytest_gate", "stdout": "...\n41 passed in 1.00s\n"},
                {"name": "acceptance_artifact", "artifact_summary": {"passed": 24, "total": 24}},
                {"name": "postgres_smoke", "ok": True},
                {
                    "name": "benchmark_artifact",
                    "ok": True,
                    "policy_checks": {
                        "core_memory_accuracy": {"value": 1.0},
                        "adversarial_robustness": {"value": 1.0},
                        "person_isolation": {"value": 1.0},
                        "operator_readiness_pass_rate": {"value": 1.0},
                    },
                    "artifact_summary": {
                        "artifact_type": "eval_benchmark_artifact",
                        "benchmark_metrics": {
                            "core_memory_accuracy": 1.0,
                            "adversarial_robustness": 1.0,
                            "person_isolation": 1.0,
                        },
                    },
                },
            ],
        }

    def fake_run(command, cwd, capture_output, text, check):
        joined = " ".join(command)
        if "rev-parse --abbrev-ref HEAD" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="main\n", stderr="")
        if "remote get-url origin" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.com/repo.git\n", stderr="")
        if "status --porcelain" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if list(command[:3]) == [str(command[0]), "-m", "pytest"]:
            if tuple(command[4:]) == CONTRACT_STATUS_TEST_FILES:
                return subprocess.CompletedProcess(command, 0, stdout="...\n46 passed in 0.50s\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="...\n262 passed in 5.00s\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("memco.local_artifacts.run_release_check", fake_run_release_check)
    monkeypatch.setattr("memco.local_artifacts.run_strict_release_check", fake_run_strict_release_check)
    monkeypatch.setattr("memco.local_artifacts.subprocess.run", fake_run)

    refresh_local_artifacts(
        project_root=project_root,
        postgres_database_url="postgresql://example/postgres",
    )

    assert os.environ.get("MEMCO_RUN_LIVE_SMOKE") == "1"

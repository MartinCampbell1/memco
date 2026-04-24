from __future__ import annotations

import json
import subprocess
from pathlib import Path

import memco.release_check as release_check_module
from memco.config import Settings, write_settings
from memco.release_check import (
    ACTIVE_GATE_TEST_FILES,
    _run_benchmark_gate,
    _run_eval_gate,
    _run_operator_safety_gate,
    _run_runtime_policy_gate,
    _run_storage_contract_gate,
    resolve_repo_project_root,
    run_release_check,
    run_release_readiness_check,
    run_strict_release_check,
)


def _write_live_runtime_settings(project_root: Path) -> None:
    settings = Settings(root=project_root)
    settings.storage.engine = "postgres"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = "secret"
    settings.api.auth_token = "memco-token"
    settings.backup_path.parent.mkdir(parents=True, exist_ok=True)
    settings.backup_path.write_text("backup", encoding="utf-8")
    write_settings(settings)


def test_module_main_runs_quick_release_check(monkeypatch, tmp_path, capsys):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    output_path = tmp_path / "release-check.json"
    captured: dict[str, object] = {}

    def fake_run_release_check(*, project_root, include_eval, include_realistic_eval=False, postgres_database_url=None):
        captured["project_root"] = project_root
        captured["include_eval"] = include_eval
        captured["include_realistic_eval"] = include_realistic_eval
        captured["postgres_database_url"] = postgres_database_url
        return {
            "artifact_type": "repo_local_release_check",
            "ok": True,
            "gate_type": "quick-repo-local",
            "steps": [],
        }

    monkeypatch.chdir(project_root)
    monkeypatch.setenv("MEMCO_RELEASE_CHECK_OUTPUT", str(output_path))
    monkeypatch.setattr("memco.release_check.resolve_repo_project_root", lambda root: root)
    monkeypatch.setattr("memco.release_check.run_release_check", fake_run_release_check)

    assert release_check_module._main() == 0
    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["artifact_type"] == "repo_local_release_check"
    assert payload["artifact_path"] == str(output_path.resolve())
    assert saved == payload
    assert captured == {
        "project_root": project_root.resolve(),
        "include_eval": True,
        "include_realistic_eval": False,
        "postgres_database_url": None,
    }


def test_run_release_check_runs_pytest_gate_and_acceptance(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()
    _write_live_runtime_settings(project_root)
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=0,
            stdout="5 passed\n",
            stderr="",
        ),
    )

    seen_roots: list[Path] = []

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            seen_roots.append(root)

        def run_acceptance(self, root: Path) -> dict:
            seen_roots.append(root)
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = run_release_check(project_root=project_root, eval_root=eval_root, include_eval=True)

    assert result["artifact_type"] == "repo_local_release_check"
    assert result["ok"] is True
    assert result["gate_type"] == "quick-repo-local"
    assert result["generated_at"]
    assert result["artifact_context"]["runtime_mode"] == "repo-local"
    assert result["artifact_context"]["config_source"]["exists"] is True
    assert result["artifact_context"]["env_overrides"]["used"] is False
    assert result["artifact_context"]["live_smoke"]["requested"] is False
    assert result["artifact_context"]["live_smoke"]["ran"] is False
    assert result["artifact_context"]["freshness"]["status"] == "current_at_generation"
    assert result["include_pytest"] is True
    assert [step["name"] for step in result["steps"]] == ["runtime_policy", "storage_contract", "operator_safety", "pytest_gate", "acceptance_artifact"]
    assert result["steps"][0]["ok"] is True
    assert result["steps"][1]["ok"] is True
    assert result["steps"][1]["storage_role"] == "primary"
    assert result["steps"][2]["ok"] is True
    assert result["steps"][3]["command"][-len(ACTIVE_GATE_TEST_FILES) :] == list(ACTIVE_GATE_TEST_FILES)
    assert result["steps"][4]["artifact_summary"]["failed"] == 0
    assert seen_roots == [eval_root, eval_root]


def test_run_release_check_skips_eval_when_pytest_gate_fails(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    _write_live_runtime_settings(project_root)

    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=1,
            stdout="1 failed\n",
            stderr="boom\n",
        ),
    )

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:  # pragma: no cover
            raise AssertionError("eval should not run when pytest gate fails")

        def run_acceptance(self, root: Path) -> dict:  # pragma: no cover
            raise AssertionError("eval should not run when pytest gate fails")

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = run_release_check(project_root=project_root, include_eval=True)

    assert result["ok"] is False
    assert result["steps"][3]["ok"] is False
    assert result["steps"][4]["skipped"] is True
    assert result["steps"][4]["reason"] == "pytest_gate_failed"


def test_run_release_check_can_run_acceptance_without_pytest(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()
    _write_live_runtime_settings(project_root)
    seen_roots: list[Path] = []
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("pytest gate should not run")

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            seen_roots.append(root)

        def run_acceptance(self, root: Path) -> dict:
            seen_roots.append(root)
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.subprocess.run", fail_if_called)
    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = run_release_check(
        project_root=project_root,
        eval_root=eval_root,
        include_pytest=False,
        include_eval=True,
    )

    assert result["ok"] is True
    assert result["include_pytest"] is False
    assert result["include_eval"] is True
    assert [step["name"] for step in result["steps"]] == ["runtime_policy", "storage_contract", "operator_safety", "acceptance_artifact"]
    assert seen_roots == [eval_root, eval_root]


def test_run_release_check_requires_at_least_one_step(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()

    try:
        run_release_check(project_root=project_root, include_pytest=False, include_eval=False)
    except ValueError as exc:
        assert "at least one enabled step" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError when all release-check steps are disabled")


def test_run_release_check_can_include_realistic_personal_memory_eval(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()
    _write_live_runtime_settings(project_root)
    seen: dict[str, Path] = {}

    def fake_personal_eval(*, project_root: Path, eval_root: Path) -> dict:
        seen["project_root"] = project_root
        seen["eval_root"] = eval_root
        return {
            "name": "personal_memory_eval_artifact",
            "ok": True,
            "artifact_summary": {"total": 400, "failed": 0},
        }

    monkeypatch.setattr("memco.release_check._run_personal_memory_eval_gate", fake_personal_eval)

    result = run_release_check(
        project_root=project_root,
        eval_root=eval_root,
        include_pytest=False,
        include_eval=False,
        include_realistic_eval=True,
    )

    assert result["ok"] is True
    assert result["include_realistic_eval"] is True
    assert [step["name"] for step in result["steps"]] == [
        "runtime_policy",
        "storage_contract",
        "operator_safety",
        "personal_memory_eval_artifact",
    ]
    assert seen["project_root"] == project_root
    assert seen["eval_root"] == eval_root / "personal-memory-eval"


def test_run_release_check_fixture_ok_is_not_release_eligible(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=0,
            stdout="5 passed\n",
            stderr="",
        ),
    )

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            seen["acceptance_seed"] = root

        def run_acceptance(self, root: Path) -> dict:
            seen["acceptance_run"] = root
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 1,
                "passed": 1,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 1, "passed_cases": 1, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 1, "cases_with_evidence": 1, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 1, "avg": 1, "p95": 1},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 1,
                "behavior_checks_passed": 1,
                "groups": [{"name": "supported_fact", "total": 1, "passed": 1, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = run_release_check(
        project_root=project_root,
        eval_root=eval_root,
        include_pytest=True,
        include_eval=True,
        fixture_ok=True,
    )

    assert result["ok"] is True
    assert result["artifact_type"] == "fixture_release_check"
    assert result["gate_type"] == "fixture-ok"
    assert result["fixture_only"] is True
    assert result["release_eligible"] is False
    assert result["artifact_context"]["runtime_mode"] == "fixture"
    assert result["artifact_context"]["fixture_only"] is True
    assert result["artifact_context"]["release_eligible"] is False
    assert result["steps"][0]["fixture_only"] is True
    assert result["steps"][0]["release_eligible"] is False
    assert result["steps"][1]["storage_engine"] == "sqlite"
    assert result["steps"][2]["reason"] == "fixture-ok mode intentionally does not require live operator secrets"


def test_run_release_check_can_run_optional_postgres_smoke(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    postgres_root = tmp_path / "postgres-runtime"
    project_root.mkdir()
    _write_live_runtime_settings(project_root)
    seen_roots: list[Path] = []
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=0,
            stdout="5 passed\n",
            stderr="",
        ),
    )

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            seen_roots.append(root)

        def run_acceptance(self, root: Path) -> dict:
            seen_roots.append(root)
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)
    monkeypatch.setattr(
        "memco.release_check.run_postgres_smoke",
        lambda **kwargs: {
            "health": {"ok": True, "storage_engine": "postgres", "database_target": kwargs["database_url"]},
            "schema_migrations": 1,
            "database_url": kwargs["database_url"],
            "root": str(kwargs["root"]),
            "port": kwargs["port"] or 8788,
        },
    )

    result = run_release_check(
        project_root=project_root,
        eval_root=eval_root,
        include_pytest=True,
        include_eval=True,
        postgres_database_url="postgresql://example/postgres",
        postgres_root=postgres_root,
        postgres_port=8788,
    )

    assert result["ok"] is True
    assert result["artifact_type"] == "canonical_postgres_release_check"
    assert result["gate_type"] == "canonical-postgres"
    assert result["include_postgres_smoke"] is True
    assert [step["name"] for step in result["steps"]] == ["runtime_policy", "storage_contract", "operator_safety", "pytest_gate", "acceptance_artifact", "postgres_smoke"]
    assert result["steps"][1]["storage_role"] == "primary"
    assert result["steps"][2]["ok"] is True
    assert result["steps"][4]["storage_engine"] == "postgres"
    assert result["steps"][4]["storage_role"] == "primary"
    assert result["steps"][5]["schema_migrations"] == 1
    assert result["steps"][5]["health"]["storage_engine"] == "postgres"
    assert seen_roots == [eval_root, eval_root]


def test_run_release_check_can_run_optional_live_smoke(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    postgres_root = tmp_path / "postgres-runtime"
    project_root.mkdir()
    _write_live_runtime_settings(project_root)
    monkeypatch.setenv("MEMCO_RUN_LIVE_SMOKE", "1")
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)
    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=0,
            stdout="5 passed\n",
            stderr="",
        ),
    )

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            return None

        def run_acceptance(self, root: Path) -> dict:
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)
    monkeypatch.setattr(
        "memco.release_check.run_postgres_smoke",
        lambda **kwargs: {
            "health": {"ok": True, "storage_engine": "postgres", "database_target": kwargs["database_url"]},
            "schema_migrations": 1,
            "database_url": kwargs["database_url"],
            "root": str(kwargs["root"]),
            "port": kwargs["port"] or 8788,
        },
    )
    monkeypatch.setattr(
        "memco.release_check.run_live_operator_smoke",
        lambda **kwargs: {
            "artifact_type": "live_operator_smoke",
            "ok": True,
            "provider": "openai-compatible",
            "model": "gpt-5.4-mini",
            "storage_engine": "postgres",
            "storage_role": "primary",
            "root": str(kwargs["root"]),
            "artifact_path": str(kwargs["output_path"]),
            "failures": [],
            "steps": [{"name": "api_queries", "ok": True}],
        },
    )

    result = run_release_check(
        project_root=project_root,
        eval_root=eval_root,
        include_pytest=True,
        include_eval=True,
        postgres_database_url="postgresql://example/postgres",
        postgres_root=postgres_root,
    )

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == [
        "runtime_policy",
        "storage_contract",
        "operator_safety",
        "pytest_gate",
        "acceptance_artifact",
        "postgres_smoke",
        "live_operator_smoke",
    ]
    assert result["steps"][6]["ok"] is True
    assert result["steps"][6]["artifact_summary"]["artifact_type"] == "live_operator_smoke"
    assert result["steps"][6]["artifact_summary"]["artifact_context"]["live_smoke"]["requested"] is True
    assert result["steps"][6]["artifact_summary"]["artifact_context"]["live_smoke"]["ran"] is True
    assert result["steps"][6]["artifact_path"].endswith("live-operator-smoke-current.json")


def test_run_release_check_rejects_canonical_postgres_gate_without_eval(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()

    try:
        run_release_check(
            project_root=project_root,
            include_pytest=True,
            include_eval=False,
            postgres_database_url="postgresql://example/postgres",
        )
    except ValueError as exc:
        assert "canonical postgres release-check requires both pytest and eval steps" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError when canonical Postgres gate disables eval")


def test_run_runtime_policy_gate_rejects_live_mock_provider(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.llm.provider = "mock"
    settings.llm.model = "fixture"
    settings.llm.allow_mock_provider = True
    write_settings(settings)

    result = _run_runtime_policy_gate(project_root=project_root)

    assert result["name"] == "runtime_policy"
    assert result["ok"] is False
    assert result["provider"] == "mock"
    assert result["runtime_profile"] == "repo-local"
    assert result["credentials_present"] is False
    assert result["base_url_present"] is False
    assert result["provider_configured"] is False
    assert result["fixture_only"] is True
    assert result["release_eligible"] is False
    assert "fixture-only" in result["reason"]


def test_run_storage_contract_gate_rejects_repo_local_sqlite_fallback(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.storage.engine = "sqlite"
    write_settings(settings)

    result = _run_storage_contract_gate(project_root=project_root)

    assert result["name"] == "storage_contract"
    assert result["ok"] is False
    assert result["runtime_profile"] == "repo-local"
    assert result["storage_engine"] == "sqlite"
    assert result["storage_contract_engine"] == "postgres"
    assert result["storage_role"] == "fallback"
    assert "fallback storage" in result["reason"]


def test_run_storage_contract_gate_accepts_fixture_sqlite_fallback(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.runtime.profile = "fixture"
    settings.storage.engine = "sqlite"
    write_settings(settings)

    result = _run_storage_contract_gate(project_root=project_root)

    assert result["name"] == "storage_contract"
    assert result["ok"] is True
    assert result["runtime_profile"] == "fixture"
    assert result["storage_engine"] == "sqlite"
    assert result["storage_role"] == "fallback"
    assert "fixture runtime" in result["reason"]


def test_run_operator_safety_gate_rejects_repo_local_missing_token_and_backup(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.storage.engine = "postgres"
    settings.api.auth_token = ""
    write_settings(settings)

    result = _run_operator_safety_gate(project_root=project_root)

    assert result["name"] == "operator_safety"
    assert result["ok"] is False
    assert result["runtime_profile"] == "repo-local"
    assert result["api_token_configured"] is False
    assert result["backup_path_exists"] is False


def test_run_operator_safety_gate_accepts_repo_local_with_token_and_backup(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.storage.engine = "postgres"
    settings.api.auth_token = "memco-token"
    backup_path = settings.backup_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text("backup", encoding="utf-8")
    write_settings(settings)

    result = _run_operator_safety_gate(project_root=project_root)

    assert result["name"] == "operator_safety"
    assert result["ok"] is True
    assert result["api_token_configured"] is True
    assert result["backup_path_exists"] is True


def test_run_runtime_policy_gate_rejects_missing_openai_compatible_api_key(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.llm.provider = "openai-compatible"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = ""
    write_settings(settings)

    result = _run_runtime_policy_gate(project_root=project_root)

    assert result["name"] == "runtime_policy"
    assert result["ok"] is False
    assert result["provider"] == "openai-compatible"
    assert result["runtime_profile"] == "repo-local"
    assert result["base_url_present"] is True
    assert result["credentials_present"] is False
    assert result["provider_configured"] is False
    assert result["release_eligible"] is False
    assert result["checkout_status"]["release_eligible"] is False
    assert result["operator_runtime_status"]["release_eligible"] is False
    assert result["env_overrides"]["used"] is False
    assert result["config_only_red_operator_green"] is False
    assert result["status_source"] == "config-only"
    assert "api_key" in result["reason"]


def test_run_runtime_policy_gate_marks_env_injected_operator_green(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.llm.provider = "openai-compatible"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = ""
    write_settings(settings)
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")

    result = _run_runtime_policy_gate(project_root=project_root)

    assert result["name"] == "runtime_policy"
    assert result["ok"] is True
    assert result["release_eligible"] is True
    assert result["checkout_status"]["release_eligible"] is False
    assert result["checkout_status"]["credentials_present"] is False
    assert result["operator_runtime_status"]["release_eligible"] is True
    assert result["operator_runtime_status"]["credentials_present"] is True
    assert result["env_overrides"]["used"] is True
    assert "MEMCO_LLM_API_KEY" in result["env_overrides"]["present_keys"]
    assert result["env_overrides"]["live_credentials_present"] is True
    assert result["config_only_red_operator_green"] is True
    assert result["status_source"] == "env-injected"


def test_run_runtime_policy_gate_does_not_count_base_url_as_live_credential(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.llm.provider = "openai-compatible"
    settings.llm.base_url = ""
    settings.llm.api_key = ""
    write_settings(settings)
    monkeypatch.setenv("MEMCO_LLM_BASE_URL", "https://router.example/v1")

    result = _run_runtime_policy_gate(project_root=project_root)

    assert result["ok"] is False
    assert result["operator_runtime_status"]["base_url_present"] is True
    assert result["operator_runtime_status"]["credentials_present"] is False
    assert result["env_overrides"]["used"] is True
    assert "MEMCO_LLM_BASE_URL" in result["env_overrides"]["present_keys"]
    assert result["env_overrides"]["live_credentials_present"] is False
    assert result["env_overrides"]["live_credential_keys"] == []


def test_run_runtime_policy_gate_does_not_count_empty_env_key_as_live_credential(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.llm.provider = "openai-compatible"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = ""
    write_settings(settings)
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "")

    result = _run_runtime_policy_gate(project_root=project_root)

    assert result["ok"] is False
    assert result["operator_runtime_status"]["credentials_present"] is False
    assert result["env_overrides"]["used"] is True
    assert "MEMCO_LLM_API_KEY" in result["env_overrides"]["present_keys"]
    assert result["env_overrides"]["live_credentials_present"] is False
    assert result["env_overrides"]["live_credential_keys"] == []


def test_run_runtime_policy_gate_rejects_missing_openai_compatible_base_url(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.llm.provider = "openai-compatible"
    settings.llm.base_url = "   "
    settings.llm.api_key = "secret"
    write_settings(settings)

    result = _run_runtime_policy_gate(project_root=project_root)

    assert result["name"] == "runtime_policy"
    assert result["ok"] is False
    assert result["provider"] == "openai-compatible"
    assert result["runtime_profile"] == "repo-local"
    assert result["base_url_present"] is False
    assert result["credentials_present"] is True
    assert result["provider_configured"] is False
    assert result["release_eligible"] is False
    assert "base_url" in result["reason"]


def test_run_release_check_stays_fail_closed_when_live_runtime_uses_mock(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    settings = Settings(root=project_root)
    settings.llm.provider = "mock"
    settings.llm.model = "fixture"
    settings.llm.allow_mock_provider = True
    write_settings(settings)
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=0,
            stdout="5 passed\n",
            stderr="",
        ),
    )

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            return None

        def run_acceptance(self, root: Path) -> dict:
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = run_release_check(project_root=project_root, eval_root=eval_root, include_eval=True)

    assert result["ok"] is False
    assert result["steps"][0]["name"] == "runtime_policy"
    assert result["steps"][0]["ok"] is False
    assert result["steps"][1]["ok"] is True
    assert result["steps"][2]["ok"] is False
    assert result["steps"][4]["ok"] is True


def test_run_release_check_stays_fail_closed_when_repo_local_runtime_uses_sqlite_fallback(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    settings = Settings(root=project_root)
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = "secret"
    settings.storage.engine = "sqlite"
    write_settings(settings)
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    monkeypatch.setattr(
        "memco.release_check.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=kwargs.get("args", args[0] if args else []),
            returncode=0,
            stdout="5 passed\n",
            stderr="",
        ),
    )

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            return None

        def run_acceptance(self, root: Path) -> dict:
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = run_release_check(project_root=project_root, eval_root=eval_root, include_eval=True)

    assert result["ok"] is False
    assert result["steps"][0]["ok"] is True
    assert result["steps"][1]["name"] == "storage_contract"
    assert result["steps"][1]["ok"] is False
    assert result["steps"][1]["storage_role"] == "fallback"
    assert result["steps"][4]["ok"] is True


def test_resolve_repo_project_root_finds_parent_checkout(tmp_path):
    repo_root = tmp_path / "memco"
    (repo_root / "src" / "memco").mkdir(parents=True)
    (repo_root / "tests").mkdir()
    (repo_root / "pyproject.toml").write_text("[project]\nname='memco'\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Memco\n", encoding="utf-8")
    nested = repo_root / "src" / "memco" / "subdir"
    nested.mkdir()

    resolved = resolve_repo_project_root(nested)

    assert resolved == repo_root


def test_resolve_repo_project_root_fails_outside_checkout(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    try:
        resolve_repo_project_root(outside)
    except ValueError as exc:
        assert "Could not resolve a Memco repo root" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError outside the repo checkout")


def test_run_eval_gate_bootstraps_runtime_before_eval(monkeypatch, tmp_path):
    eval_root = tmp_path / "eval-runtime"
    order: list[tuple[str, Path]] = []
    settings = Settings(root=eval_root)

    monkeypatch.setattr("memco.release_check.load_settings", lambda root: settings)

    def fake_ensure_runtime(settings):
        order.append(("ensure_runtime", settings.root))
        return settings

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            order.append(("seed_fixture_data", root))

        def run_acceptance(self, root: Path) -> dict:
            order.append(("run", root))
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.ensure_runtime", fake_ensure_runtime)
    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = _run_eval_gate(eval_root=eval_root)

    assert result["ok"] is True
    assert result["storage_engine"] == "sqlite"
    assert result["storage_contract_engine"] == "postgres"
    assert result["storage_role"] == "fallback"
    assert result["runtime_profile"] == "fixture"
    assert order == [
        ("ensure_runtime", eval_root),
        ("seed_fixture_data", eval_root),
        ("run", eval_root),
    ]


def test_run_eval_gate_uses_postgres_when_runtime_config_requests_it(monkeypatch, tmp_path):
    eval_root = tmp_path / "eval-runtime"
    settings = Settings(root=eval_root)
    settings.storage.engine = "postgres"
    settings.storage.database_url = "postgresql://memco:memco@db:5432/memco"
    write_settings(settings)
    seen: dict[str, str] = {}

    def fake_ensure_runtime(selected: Settings):
        seen["storage_engine"] = selected.storage.engine
        seen["database_target"] = selected.database_target
        return selected

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            assert root == eval_root

        def run_acceptance(self, root: Path) -> dict:
            assert root == eval_root
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.ensure_runtime", fake_ensure_runtime)
    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = _run_eval_gate(eval_root=eval_root)

    assert result["ok"] is True
    assert seen == {
        "storage_engine": "postgres",
        "database_target": "postgresql://memco:memco@db:5432/memco",
    }
    assert result["storage_engine"] == "postgres"
    assert result["storage_contract_engine"] == "postgres"
    assert result["storage_role"] == "primary"
    assert result["runtime_profile"] == "fixture"


def test_run_eval_gate_can_force_postgres_storage(monkeypatch, tmp_path):
    eval_root = tmp_path / "eval-runtime"
    seen: dict[str, str] = {}

    def fake_ensure_runtime(selected: Settings):
        seen["storage_engine"] = selected.storage.engine
        seen["database_target"] = selected.database_target
        return selected

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            assert root == eval_root

        def run_acceptance(self, root: Path) -> dict:
            assert root == eval_root
            return {
                "artifact_type": "eval_acceptance_artifact",
                "release_scope": "private-single-user",
                "total": 20,
                "passed": 20,
                "failed": 0,
                "pass_rate": 1.0,
                "accuracy": 1.0,
                "refusal_correctness": {"total_cases": 3, "passed_cases": 3, "rate": 1.0},
                "evidence_coverage": {"cases_with_hits": 10, "cases_with_evidence": 10, "rate": 1.0},
                "retrieval_latency_ms": {"min": 1, "max": 2, "avg": 1, "p95": 2},
                "token_accounting": {"status": "tracked"},
                "behavior_checks_total": 2,
                "behavior_checks_passed": 2,
                "groups": [{"name": "supported_fact", "total": 2, "passed": 2, "pass_rate": 1.0}],
            }

    monkeypatch.setattr("memco.release_check.ensure_runtime", fake_ensure_runtime)
    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = _run_eval_gate(
        eval_root=eval_root,
        storage_engine="postgres",
        database_url="postgresql://memco:memco@db:5432/memco",
    )

    assert result["ok"] is True
    assert seen == {
        "storage_engine": "postgres",
        "database_target": "postgresql://memco:memco@db:5432/memco",
    }
    assert result["storage_engine"] == "postgres"
    assert result["storage_role"] == "primary"
    assert result["runtime_profile"] == "fixture"


def test_run_benchmark_gate_emits_threshold_checks(monkeypatch, tmp_path):
    eval_root = tmp_path / "benchmark-runtime"
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            assert root == eval_root

        def run_benchmark(self, root: Path) -> dict:
            assert root == eval_root
            return {
                "artifact_type": "eval_benchmark_artifact",
                "release_scope": "benchmark-only",
                "benchmark_scope": "internal-approximation",
                "benchmark_disclaimer": "synthetic benchmark; not paper-equivalent",
                "benchmark_metrics": {
                    "core_memory_accuracy": 1.0,
                    "adversarial_robustness": 1.0,
                    "person_isolation": 1.0,
                    "unsupported_premise_supported_count": 0,
                    "positive_answers_missing_evidence_ids": 0,
                    "retrieval_latency_ms": {"min": 0, "max": 1, "avg": 0.1, "p50": 0, "p95": 1},
                    "token_accounting_by_stage": {
                        "extraction": {"status": "measured_delta", "input_tokens": 0, "output_tokens": 0},
                        "planner": {"status": "not_instrumented", "input_tokens": 0, "output_tokens": 0},
                        "retrieval": {"status": "not_instrumented", "input_tokens": 0, "output_tokens": 0},
                        "answer": {"status": "not_instrumented", "input_tokens": 0, "output_tokens": 0},
                    },
                    "extra_prompt_tokens": 0,
                },
                "benchmark_thresholds": {
                    "core_memory_accuracy_min": 0.9,
                    "adversarial_robustness_min": 0.95,
                    "person_isolation_min": 0.99,
                    "unsupported_premise_supported_count_max": 0,
                    "positive_answers_missing_evidence_ids_max": 0,
                },
                "operator_readiness_metrics": {
                    "pass_rate": 1.0,
                    "total": 5,
                    "passed": 5,
                    "groups": ["supported_fact"],
                },
                "benchmark_sets": {},
                "benchmark_cases": [],
                "operator_readiness_cases": [],
                "domain_reports": {},
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = _run_benchmark_gate(eval_root=eval_root)

    assert result["name"] == "benchmark_artifact"
    assert result["ok"] is True
    assert result["policy_checks"]["core_memory_accuracy"]["ok"] is True
    assert result["policy_checks"]["person_isolation"]["ok"] is True
    assert result["policy_checks"]["unsupported_premise_supported_count"]["value"] == 0
    assert result["policy_checks"]["operator_readiness_pass_rate"]["ok"] is True
    assert result["thresholds"]["operator_readiness_pass_rate_min"] == 1.0


def test_run_benchmark_gate_fails_when_operator_readiness_is_not_green(monkeypatch, tmp_path):
    eval_root = tmp_path / "benchmark-runtime"
    monkeypatch.setattr("memco.release_check.ensure_runtime", lambda settings: settings)

    class _FakeEvalService:
        def seed_fixture_data(self, root: Path) -> None:
            assert root == eval_root

        def run_benchmark(self, root: Path) -> dict:
            assert root == eval_root
            return {
                "artifact_type": "eval_benchmark_artifact",
                "release_scope": "benchmark-only",
                "benchmark_metrics": {
                    "core_memory_accuracy": 1.0,
                    "adversarial_robustness": 1.0,
                    "person_isolation": 1.0,
                    "unsupported_premise_supported_count": 0,
                    "positive_answers_missing_evidence_ids": 0,
                },
                "operator_readiness_metrics": {
                    "pass_rate": 0.8,
                    "total": 5,
                    "passed": 4,
                    "failures": [{"name": "pending-review", "failures": ["pending_review_leakage"]}],
                },
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = _run_benchmark_gate(eval_root=eval_root)

    assert result["ok"] is False
    assert result["policy_checks"]["operator_readiness_pass_rate"] == {
        "value": 0.8,
        "threshold": 1.0,
        "ok": False,
    }
    assert result["artifact_summary"]["operator_readiness_metrics"]["failures"]


def test_run_strict_release_check_requires_benchmark_success(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()

    monkeypatch.setattr(
        "memco.release_check.run_release_check",
        lambda **kwargs: {
            "artifact_type": "canonical_postgres_release_check",
            "ok": True,
            "gate_type": "canonical-postgres",
            "steps": [
                {"name": "runtime_policy", "ok": True},
                {"name": "storage_contract", "ok": True, "storage_role": "primary"},
                {"name": "operator_safety", "ok": True, "api_token_configured": True, "backup_path_exists": True},
                {"name": "pytest_gate", "ok": True, "stdout": "5 passed\n"},
                {"name": "acceptance_artifact", "ok": True, "artifact_summary": {"passed": 24, "total": 24}},
                {"name": "postgres_smoke", "ok": True},
            ],
        },
    )
    monkeypatch.setattr(
        "memco.release_check._run_benchmark_gate",
        lambda **kwargs: {
            "name": "benchmark_artifact",
            "ok": False,
            "thresholds": {},
            "policy_checks": {
                "core_memory_accuracy": {"value": 0.85, "threshold": 0.9, "ok": False},
            },
            "artifact_summary": {
                "artifact_type": "eval_benchmark_artifact",
                "benchmark_metrics": {"core_memory_accuracy": 0.85},
            },
        },
    )

    result = run_strict_release_check(
        project_root=project_root,
        eval_root=eval_root,
        postgres_database_url="postgresql://example/postgres",
    )

    assert result["artifact_type"] == "strict_quality_release_check"
    assert result["gate_type"] == "strict-quality"
    assert result["benchmark_required"] is True
    assert result["ok"] is False
    assert [step["name"] for step in result["steps"]] == [
        "runtime_policy",
        "storage_contract",
        "operator_safety",
        "pytest_gate",
        "acceptance_artifact",
        "postgres_smoke",
        "benchmark_artifact",
    ]


def test_run_release_readiness_check_requires_live_smoke_request(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()

    monkeypatch.setattr(
        "memco.release_check.run_strict_release_check",
        lambda **kwargs: {
            "artifact_type": "strict_quality_release_check",
            "ok": True,
            "gate_type": "strict-quality",
            "steps": [{"name": "benchmark_artifact", "ok": True}],
        },
    )

    result = run_release_readiness_check(
        project_root=project_root,
        postgres_database_url="postgresql://example/postgres",
    )

    assert result["artifact_type"] == "release_readiness_check"
    assert result["gate_type"] == "release-grade"
    assert result["live_smoke_required"] is True
    assert result["artifact_context"]["live_smoke"]["required"] is True
    assert result["artifact_context"]["live_smoke"]["requested"] is False
    assert result["artifact_context"]["live_smoke"]["ran"] is False
    assert result["ok"] is False
    assert result["steps"][-1]["name"] == "live_operator_smoke"
    assert result["steps"][-1]["ok"] is False
    assert result["steps"][-1]["skipped"] is True
    assert result["steps"][-1]["reason"] == "live_smoke_required_for_release_claim"


def test_run_release_readiness_check_stays_red_when_prior_gate_fails(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    monkeypatch.setenv("MEMCO_RUN_LIVE_SMOKE", "1")

    monkeypatch.setattr(
        "memco.release_check.run_strict_release_check",
        lambda **kwargs: {
            "artifact_type": "strict_quality_release_check",
            "ok": False,
            "gate_type": "strict-quality",
            "steps": [{"name": "runtime_policy", "ok": False}],
        },
    )

    result = run_release_readiness_check(
        project_root=project_root,
        postgres_database_url="postgresql://example/postgres",
    )

    assert result["ok"] is False
    assert result["steps"][-1]["name"] == "live_operator_smoke"
    assert result["steps"][-1]["ok"] is False
    assert result["steps"][-1]["skipped"] is True
    assert result["steps"][-1]["reason"] == "prior_gate_failed"


def test_run_release_readiness_check_passes_only_with_live_smoke_success(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    monkeypatch.setenv("MEMCO_RUN_LIVE_SMOKE", "1")

    monkeypatch.setattr(
        "memco.release_check.run_strict_release_check",
        lambda **kwargs: {
            "artifact_type": "strict_quality_release_check",
            "ok": True,
            "gate_type": "strict-quality",
            "steps": [{"name": "benchmark_artifact", "ok": True}],
        },
    )
    monkeypatch.setattr(
        "memco.release_check._run_live_smoke_gate",
        lambda **kwargs: {
            "name": "live_operator_smoke",
            "ok": True,
            "required": True,
            "artifact_path": str(kwargs["output_path"]),
            "artifact_summary": {"artifact_type": "live_operator_smoke", "steps": [], "failures": []},
        },
    )

    result = run_release_readiness_check(
        project_root=project_root,
        postgres_database_url="postgresql://example/postgres",
    )

    assert result["ok"] is True
    assert result["steps"][-1]["name"] == "live_operator_smoke"
    assert result["steps"][-1]["ok"] is True
    assert result["steps"][-1]["required"] is True
    assert result["artifact_context"]["live_smoke"]["required"] is True
    assert result["artifact_context"]["live_smoke"]["requested"] is True
    assert result["artifact_context"]["live_smoke"]["ran"] is True
    assert result["steps"][-1]["artifact_path"].endswith("live-operator-smoke-current.json")

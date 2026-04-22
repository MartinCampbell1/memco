from __future__ import annotations

import subprocess
from pathlib import Path

from memco.config import Settings, write_settings
from memco.release_check import (
    ACTIVE_GATE_TEST_FILES,
    _run_benchmark_gate,
    _run_eval_gate,
    _run_runtime_policy_gate,
    resolve_repo_project_root,
    run_release_check,
    run_strict_release_check,
)


def test_run_release_check_runs_pytest_gate_and_acceptance(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()
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
    assert result["include_pytest"] is True
    assert [step["name"] for step in result["steps"]] == ["runtime_policy", "pytest_gate", "acceptance_artifact"]
    assert result["steps"][0]["ok"] is True
    assert result["steps"][1]["command"][-len(ACTIVE_GATE_TEST_FILES) :] == list(ACTIVE_GATE_TEST_FILES)
    assert result["steps"][2]["artifact_summary"]["failed"] == 0
    assert seen_roots == [eval_root, eval_root]


def test_run_release_check_skips_eval_when_pytest_gate_fails(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()

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
    assert result["steps"][1]["ok"] is False
    assert result["steps"][2]["skipped"] is True
    assert result["steps"][2]["reason"] == "pytest_gate_failed"


def test_run_release_check_can_run_acceptance_without_pytest(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    project_root.mkdir()
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
    assert [step["name"] for step in result["steps"]] == ["runtime_policy", "acceptance_artifact"]
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


def test_run_release_check_can_run_optional_postgres_smoke(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    eval_root = tmp_path / "eval-runtime"
    postgres_root = tmp_path / "postgres-runtime"
    project_root.mkdir()
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
    assert [step["name"] for step in result["steps"]] == ["runtime_policy", "pytest_gate", "acceptance_artifact", "postgres_smoke"]
    assert result["steps"][2]["storage_engine"] == "postgres"
    assert result["steps"][2]["storage_role"] == "primary"
    assert result["steps"][3]["schema_migrations"] == 1
    assert result["steps"][3]["health"]["storage_engine"] == "postgres"
    assert seen_roots == [eval_root, eval_root]


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
    assert result["fixture_only"] is True
    assert result["release_eligible"] is False
    assert "fixture-only" in result["reason"]


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
    assert result["steps"][2]["ok"] is True


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
                "benchmark_sets": {},
                "benchmark_cases": [],
                "domain_reports": {},
            }

    monkeypatch.setattr("memco.release_check.EvalService", _FakeEvalService)

    result = _run_benchmark_gate(eval_root=eval_root)

    assert result["name"] == "benchmark_artifact"
    assert result["ok"] is True
    assert result["policy_checks"]["core_memory_accuracy"]["ok"] is True
    assert result["policy_checks"]["person_isolation"]["ok"] is True
    assert result["policy_checks"]["unsupported_premise_supported_count"]["value"] == 0


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
        "pytest_gate",
        "acceptance_artifact",
        "postgres_smoke",
        "benchmark_artifact",
    ]

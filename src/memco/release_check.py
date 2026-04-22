from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from memco.config import load_settings, write_settings
from memco.llm import llm_runtime_policy
from memco.postgres_smoke import run_postgres_smoke
from memco.runtime import ensure_runtime
from memco.services.eval_service import EvalService

ACTIVE_GATE_TEST_FILES = (
    "tests/test_ingest_service.py",
    "tests/test_cli_smoke.py",
    "tests/test_retrieval_logging.py",
    "tests/test_fact_lifecycle_rollback.py",
    "tests/test_docs_contract.py",
)

BENCHMARK_THRESHOLDS = {
    "core_memory_accuracy": 0.90,
    "adversarial_robustness": 0.95,
    "person_isolation": 0.99,
    "unsupported_premise_supported_count": 0,
    "positive_answers_missing_evidence_ids": 0,
}


def resolve_repo_project_root(start: Path) -> Path:
    origin = start.resolve()
    candidate = origin if origin.is_dir() else origin.parent
    markers = (
        ("pyproject.toml",),
        ("README.md",),
        ("src", "memco"),
        ("tests",),
    )

    for current in (candidate, *candidate.parents):
        if all((current.joinpath(*parts)).exists() for parts in markers):
            return current

    raise ValueError(
        f"Could not resolve a Memco repo root from {origin}. "
        "Run this command from inside the Memco checkout or pass --project-root."
    )


def _run_pytest_gate(*, project_root: Path) -> dict:
    command = [sys.executable, "-m", "pytest", "-q", *ACTIVE_GATE_TEST_FILES]
    completed = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "name": "pytest_gate",
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _run_runtime_policy_gate(*, project_root: Path) -> dict:
    settings = load_settings(project_root)
    policy = llm_runtime_policy(settings)
    return {
        "name": "runtime_policy",
        "ok": policy["release_eligible"],
        "root": str(project_root),
        "config_path": str(settings.config_path),
        **policy,
    }


def _run_eval_gate(
    *,
    eval_root: Path,
    storage_engine: str | None = None,
    database_url: str | None = None,
) -> dict:
    settings = load_settings(eval_root)
    settings.runtime.profile = "fixture"
    if storage_engine is not None:
        settings.storage.engine = storage_engine
    if database_url is not None:
        settings.storage.database_url = database_url
    if storage_engine is None and not settings.config_path.exists():
        settings.storage.engine = "sqlite"
    write_settings(settings)
    ensure_runtime(settings)
    service = EvalService()
    service.seed_fixture_data(eval_root)
    artifact = service.run_acceptance(eval_root)
    return {
        "name": "acceptance_artifact",
        "ok": artifact["failed"] == 0 and artifact["behavior_checks_total"] == artifact["behavior_checks_passed"],
        "root": str(eval_root),
        "storage_engine": settings.storage.engine,
        "storage_contract_engine": settings.storage.contract_engine,
        "storage_role": settings.storage_role,
        "runtime_profile": settings.runtime_profile,
        "artifact_summary": {
            "artifact_type": artifact["artifact_type"],
            "release_scope": artifact["release_scope"],
            "total": artifact["total"],
            "passed": artifact["passed"],
            "failed": artifact["failed"],
            "pass_rate": artifact["pass_rate"],
            "accuracy": artifact["accuracy"],
            "refusal_correctness": artifact["refusal_correctness"],
            "evidence_coverage": artifact["evidence_coverage"],
            "retrieval_latency_ms": artifact["retrieval_latency_ms"],
            "token_accounting": artifact["token_accounting"],
            "behavior_checks_total": artifact["behavior_checks_total"],
            "behavior_checks_passed": artifact["behavior_checks_passed"],
            "groups": artifact["groups"],
        },
    }


def _run_postgres_gate(
    *,
    project_root: Path,
    database_url: str,
    postgres_root: Path,
    port: int | None = None,
) -> dict:
    result = run_postgres_smoke(
        database_url=database_url,
        root=postgres_root,
        port=port,
        project_root=project_root,
    )
    return {
        "name": "postgres_smoke",
        "ok": True,
        "database_url": result["database_url"],
        "schema_migrations": result["schema_migrations"],
        "health": result["health"],
        "root": result["root"],
        "port": result["port"],
    }


def _benchmark_policy(artifact: dict) -> dict:
    metrics = artifact["benchmark_metrics"]
    checks = {
        "core_memory_accuracy": {
            "value": float(metrics["core_memory_accuracy"]),
            "threshold": BENCHMARK_THRESHOLDS["core_memory_accuracy"],
            "ok": float(metrics["core_memory_accuracy"]) >= BENCHMARK_THRESHOLDS["core_memory_accuracy"],
        },
        "adversarial_robustness": {
            "value": float(metrics["adversarial_robustness"]),
            "threshold": BENCHMARK_THRESHOLDS["adversarial_robustness"],
            "ok": float(metrics["adversarial_robustness"]) >= BENCHMARK_THRESHOLDS["adversarial_robustness"],
        },
        "person_isolation": {
            "value": float(metrics["person_isolation"]),
            "threshold": BENCHMARK_THRESHOLDS["person_isolation"],
            "ok": float(metrics["person_isolation"]) >= BENCHMARK_THRESHOLDS["person_isolation"],
        },
        "unsupported_premise_supported_count": {
            "value": int(metrics["unsupported_premise_supported_count"]),
            "threshold": BENCHMARK_THRESHOLDS["unsupported_premise_supported_count"],
            "ok": int(metrics["unsupported_premise_supported_count"]) <= BENCHMARK_THRESHOLDS["unsupported_premise_supported_count"],
        },
        "positive_answers_missing_evidence_ids": {
            "value": int(metrics["positive_answers_missing_evidence_ids"]),
            "threshold": BENCHMARK_THRESHOLDS["positive_answers_missing_evidence_ids"],
            "ok": int(metrics["positive_answers_missing_evidence_ids"]) <= BENCHMARK_THRESHOLDS["positive_answers_missing_evidence_ids"],
        },
    }
    return {
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "thresholds": dict(BENCHMARK_THRESHOLDS),
    }


def _run_benchmark_gate(
    *,
    eval_root: Path,
    storage_engine: str | None = None,
    database_url: str | None = None,
) -> dict:
    settings = load_settings(eval_root)
    settings.runtime.profile = "fixture"
    if storage_engine is not None:
        settings.storage.engine = storage_engine
    if database_url is not None:
        settings.storage.database_url = database_url
    if storage_engine is None and not settings.config_path.exists():
        settings.storage.engine = "sqlite"
    write_settings(settings)
    ensure_runtime(settings)
    service = EvalService()
    service.seed_fixture_data(eval_root)
    artifact = service.run_benchmark(eval_root)
    policy = _benchmark_policy(artifact)
    return {
        "name": "benchmark_artifact",
        "ok": policy["ok"],
        "root": str(eval_root),
        "storage_engine": settings.storage.engine,
        "storage_contract_engine": settings.storage.contract_engine,
        "storage_role": settings.storage_role,
        "runtime_profile": settings.runtime_profile,
        "thresholds": policy["thresholds"],
        "policy_checks": policy["checks"],
        "artifact_summary": artifact,
    }


def run_release_check(
    *,
    project_root: Path,
    eval_root: Path | None = None,
    include_pytest: bool = True,
    include_eval: bool = True,
    postgres_database_url: str | None = None,
    postgres_root: Path | None = None,
    postgres_port: int | None = None,
) -> dict:
    if not include_pytest and not include_eval and not postgres_database_url:
        raise ValueError("run_release_check requires at least one enabled step")
    if postgres_database_url and (not include_pytest or not include_eval):
        raise ValueError("canonical postgres release-check requires both pytest and eval steps")

    steps: list[dict] = []
    runtime_step = _run_runtime_policy_gate(project_root=project_root)
    steps.append(runtime_step)
    ok = runtime_step["ok"]
    pytest_step: dict | None = None

    if include_pytest:
        pytest_step = _run_pytest_gate(project_root=project_root)
        steps.append(pytest_step)
        ok = ok and pytest_step["ok"]

    if include_eval:
        if not include_pytest or (pytest_step is not None and pytest_step["ok"]):
            if eval_root is not None:
                eval_root.mkdir(parents=True, exist_ok=True)
                eval_step = _run_eval_gate(
                    eval_root=eval_root,
                    storage_engine="postgres" if postgres_database_url else None,
                    database_url=postgres_database_url,
                )
            else:
                with TemporaryDirectory(prefix="memco-release-check-") as tmpdir:
                    eval_step = _run_eval_gate(
                        eval_root=Path(tmpdir),
                        storage_engine="postgres" if postgres_database_url else None,
                        database_url=postgres_database_url,
                    )
        else:
            eval_step = {
                "name": "acceptance_artifact",
                "ok": False,
                "skipped": True,
                "reason": "pytest_gate_failed",
            }
        steps.append(eval_step)
        ok = ok and eval_step["ok"]

    if postgres_database_url:
        if ok:
            if postgres_root is not None:
                postgres_root.mkdir(parents=True, exist_ok=True)
                postgres_step = _run_postgres_gate(
                    project_root=project_root,
                    database_url=postgres_database_url,
                    postgres_root=postgres_root,
                    port=postgres_port,
                )
            else:
                with TemporaryDirectory(prefix="memco-release-check-postgres-") as tmpdir:
                    postgres_step = _run_postgres_gate(
                        project_root=project_root,
                        database_url=postgres_database_url,
                        postgres_root=Path(tmpdir),
                        port=postgres_port,
                    )
        else:
            postgres_step = {
                "name": "postgres_smoke",
                "ok": False,
                "skipped": True,
                "reason": "prior_gate_failed",
            }
        steps.append(postgres_step)
        ok = ok and postgres_step["ok"]

    return {
        "artifact_type": "canonical_postgres_release_check" if postgres_database_url else "repo_local_release_check",
        "ok": ok,
        "gate_type": "canonical-postgres" if postgres_database_url else "quick-repo-local",
        "include_pytest": include_pytest,
        "include_eval": include_eval,
        "include_postgres_smoke": bool(postgres_database_url),
        "project_root": str(project_root),
        "steps": steps,
    }


def run_strict_release_check(
    *,
    project_root: Path,
    eval_root: Path | None = None,
    postgres_database_url: str,
    postgres_root: Path | None = None,
    postgres_port: int | None = None,
) -> dict:
    if not postgres_database_url:
        raise ValueError("strict release-check requires postgres_database_url")
    if eval_root is None:
        with TemporaryDirectory(prefix="memco-strict-release-check-") as tmpdir:
            return run_strict_release_check(
                project_root=project_root,
                eval_root=Path(tmpdir),
                postgres_database_url=postgres_database_url,
                postgres_root=postgres_root,
                postgres_port=postgres_port,
            )

    eval_root.mkdir(parents=True, exist_ok=True)
    release_artifact = run_release_check(
        project_root=project_root,
        eval_root=eval_root,
        include_pytest=True,
        include_eval=True,
        postgres_database_url=postgres_database_url,
        postgres_root=postgres_root,
        postgres_port=postgres_port,
    )
    steps = list(release_artifact["steps"])
    ok = release_artifact["ok"]
    if ok:
        benchmark_step = _run_benchmark_gate(
            eval_root=eval_root,
            storage_engine="postgres",
            database_url=postgres_database_url,
        )
    else:
        benchmark_step = {
            "name": "benchmark_artifact",
            "ok": False,
            "skipped": True,
            "reason": "prior_gate_failed",
            "thresholds": dict(BENCHMARK_THRESHOLDS),
        }
    steps.append(benchmark_step)
    ok = ok and benchmark_step["ok"]
    return {
        "artifact_type": "strict_quality_release_check",
        "ok": ok,
        "gate_type": "strict-quality",
        "base_gate_type": release_artifact["gate_type"],
        "benchmark_required": True,
        "include_postgres_smoke": True,
        "project_root": str(project_root),
        "steps": steps,
    }

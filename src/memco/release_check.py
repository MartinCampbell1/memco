from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from memco.artifact_semantics import attach_artifact_context
from memco.config import load_settings, write_settings
from memco.live_smoke import run_live_operator_smoke
from memco.llm import llm_runtime_status
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

OPERATOR_READINESS_MIN_PASS_RATE = 1.0


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
    dependency_command = [sys.executable, "-m", "pip", "check"]
    dependency_completed = subprocess.run(
        dependency_command,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    command = [sys.executable, "-m", "pytest", "-q", *ACTIVE_GATE_TEST_FILES]
    if dependency_completed.returncode == 0:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        completed = subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="pytest skipped because pip check failed\n",
        )
    return {
        "name": "pytest_gate",
        "ok": dependency_completed.returncode == 0 and completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "dependency_check": {
            "name": "pip_check",
            "ok": dependency_completed.returncode == 0,
            "returncode": dependency_completed.returncode,
            "command": dependency_command,
            "stdout": dependency_completed.stdout,
            "stderr": dependency_completed.stderr,
        },
    }


def _run_runtime_policy_gate(*, project_root: Path) -> dict:
    settings = load_settings(project_root)
    status = llm_runtime_status(settings)
    policy = status["operator_runtime_status"]
    return {
        "name": "runtime_policy",
        "ok": policy["release_eligible"],
        "root": str(project_root),
        "config_path": str(settings.config_path),
        **status,
        **policy,
    }


def _run_storage_contract_gate(*, project_root: Path) -> dict:
    settings = load_settings(project_root)
    runtime_profile = settings.runtime_profile
    storage_role = settings.storage_role
    storage_engine = settings.storage.engine
    expected_engine = settings.storage.contract_engine
    operator_profile = runtime_profile == "repo-local"
    ok = not operator_profile or storage_role == "primary"
    if ok and operator_profile:
        reason = "repo-local runtime is using the primary storage contract"
    elif ok:
        reason = "fixture runtime may use fallback storage"
    else:
        reason = (
            "repo-local runtime is using fallback storage; "
            f"expected primary {expected_engine}, got {storage_engine}"
        )
    return {
        "name": "storage_contract",
        "ok": ok,
        "root": str(project_root),
        "config_path": str(settings.config_path),
        "runtime_profile": runtime_profile,
        "storage_engine": storage_engine,
        "storage_contract_engine": expected_engine,
        "storage_role": storage_role,
        "reason": reason,
    }


def _run_operator_safety_gate(*, project_root: Path) -> dict:
    settings = load_settings(project_root)
    api_token_configured = bool((settings.api.auth_token or "").strip())
    backup_path = settings.backup_path
    backup_path_exists = backup_path.exists()
    runtime_profile = settings.runtime_profile
    operator_profile = runtime_profile == "repo-local"
    ok = (not operator_profile) or (api_token_configured and backup_path_exists)
    if ok and operator_profile:
        reason = "repo-local runtime has API token configured and backup path present"
    elif ok:
        reason = "fixture runtime skips operator-safety enforcement"
    elif not api_token_configured and not backup_path_exists:
        reason = "repo-local runtime is missing API token and backup path"
    elif not api_token_configured:
        reason = "repo-local runtime is missing API token"
    else:
        reason = "repo-local runtime is missing backup path"
    return {
        "name": "operator_safety",
        "ok": ok,
        "root": str(project_root),
        "config_path": str(settings.config_path),
        "runtime_profile": runtime_profile,
        "api_token_configured": api_token_configured,
        "backup_path": str(backup_path),
        "backup_path_exists": backup_path_exists,
        "reason": reason,
    }


def _run_fixture_runtime_gate(*, project_root: Path) -> dict:
    return {
        "name": "runtime_policy",
        "ok": True,
        "root": str(project_root),
        "runtime_profile": "fixture",
        "provider": "mock",
        "model": "fixture",
        "fixture_only": True,
        "release_eligible": False,
        "reason": "fixture-ok mode is archive-safe and cannot be used as release-grade proof",
    }


def _run_fixture_storage_gate(*, project_root: Path) -> dict:
    return {
        "name": "storage_contract",
        "ok": True,
        "root": str(project_root),
        "runtime_profile": "fixture",
        "storage_engine": "sqlite",
        "storage_contract_engine": "postgres",
        "storage_role": "fallback",
        "reason": "fixture-ok mode uses isolated sqlite fixture storage",
    }


def _run_fixture_operator_safety_gate(*, project_root: Path) -> dict:
    return {
        "name": "operator_safety",
        "ok": True,
        "root": str(project_root),
        "runtime_profile": "fixture",
        "api_token_configured": False,
        "backup_path_exists": False,
        "reason": "fixture-ok mode intentionally does not require live operator secrets",
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


def _live_smoke_requested() -> bool:
    return os.environ.get("MEMCO_RUN_LIVE_SMOKE", "").strip().lower() in {"1", "true", "yes", "on"}


def _run_live_smoke_gate(
    *,
    project_root: Path,
    database_url: str,
    live_smoke_root: Path,
    output_path: Path | None = None,
    live_smoke_required: bool = False,
) -> dict:
    result = run_live_operator_smoke(
        maintenance_database_url=database_url,
        root=live_smoke_root,
        project_root=project_root,
        output_path=output_path,
    )
    attach_artifact_context(
        result,
        project_root=project_root,
        steps=[{"name": "live_operator_smoke", "ok": result["ok"], "artifact_path": result.get("artifact_path")}],
        live_smoke_requested=True,
        live_smoke_required=live_smoke_required,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "name": "live_operator_smoke",
        "ok": result["ok"],
        "root": result["root"],
        "storage_engine": result["storage_engine"],
        "storage_role": result["storage_role"],
        "provider": result["provider"],
        "model": result["model"],
        "artifact_path": result.get("artifact_path"),
        "artifact_summary": {
            "artifact_type": result["artifact_type"],
            "generated_at": result["generated_at"],
            "artifact_context": result["artifact_context"],
            "failures": result["failures"],
            "steps": result["steps"],
        },
    }


def _benchmark_policy(artifact: dict) -> dict:
    metrics = artifact["benchmark_metrics"]
    operator_metrics = artifact.get("operator_readiness_metrics") or {}
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
        "operator_readiness_pass_rate": {
            "value": float(operator_metrics.get("pass_rate", 0.0)),
            "threshold": OPERATOR_READINESS_MIN_PASS_RATE,
            "ok": float(operator_metrics.get("pass_rate", 0.0)) >= OPERATOR_READINESS_MIN_PASS_RATE,
        },
    }
    return {
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "thresholds": {
            **dict(BENCHMARK_THRESHOLDS),
            "operator_readiness_pass_rate_min": OPERATOR_READINESS_MIN_PASS_RATE,
        },
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


def _run_personal_memory_eval_gate(
    *,
    project_root: Path,
    eval_root: Path,
) -> dict:
    goldens_dir = project_root / "eval" / "personal_memory_goldens"
    settings = load_settings(eval_root)
    settings.runtime.profile = "fixture"
    settings.storage.engine = "sqlite"
    write_settings(settings)
    ensure_runtime(settings)
    artifact = EvalService().run_personal_memory(
        project_root=eval_root,
        goldens_dir=goldens_dir,
    )
    realistic_cases: list[dict] = []
    realistic_path = goldens_dir / "realistic_personal_memory_goldens.jsonl"
    if realistic_path.exists():
        for raw_line in realistic_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line:
                realistic_cases.append(json.loads(line))
    realistic_scenario_counts = {
        str(scenario): sum(1 for item in realistic_cases if item.get("scenario") == scenario)
        for scenario in sorted({item.get("scenario") for item in realistic_cases if item.get("scenario")})
    }
    return {
        "name": "personal_memory_eval_artifact",
        "ok": artifact["ok"],
        "root": str(eval_root),
        "goldens_dir": artifact["goldens_dir"],
        "artifact_summary": {
            "artifact_type": artifact["artifact_type"],
            "release_scope": artifact["release_scope"],
            "total": artifact["total"],
            "passed": artifact["passed"],
            "failed": artifact["failed"],
            "realistic_total": len(realistic_cases),
            "realistic_scenario_counts": realistic_scenario_counts,
            "metrics": artifact["metrics"],
            "policy_checks": artifact["policy_checks"],
            "dataset_count_checks": artifact["dataset_count_checks"],
            "groups": artifact["groups"],
        },
    }


def run_release_check(
    *,
    project_root: Path,
    eval_root: Path | None = None,
    include_pytest: bool = True,
    include_eval: bool = True,
    include_realistic_eval: bool = False,
    fixture_ok: bool = False,
    postgres_database_url: str | None = None,
    postgres_root: Path | None = None,
    postgres_port: int | None = None,
    include_live_smoke: bool | None = None,
) -> dict:
    if not include_pytest and not include_eval and not include_realistic_eval and not postgres_database_url:
        raise ValueError("run_release_check requires at least one enabled step")
    if fixture_ok and postgres_database_url:
        raise ValueError("fixture-ok release-check cannot include postgres_database_url")
    if postgres_database_url and (not include_pytest or not include_eval):
        raise ValueError("canonical postgres release-check requires both pytest and eval steps")

    steps: list[dict] = []
    live_smoke_requested = False
    runtime_step = _run_fixture_runtime_gate(project_root=project_root) if fixture_ok else _run_runtime_policy_gate(project_root=project_root)
    steps.append(runtime_step)
    ok = runtime_step["ok"]
    storage_step = _run_fixture_storage_gate(project_root=project_root) if fixture_ok else _run_storage_contract_gate(project_root=project_root)
    steps.append(storage_step)
    ok = ok and storage_step["ok"]
    safety_step = _run_fixture_operator_safety_gate(project_root=project_root) if fixture_ok else _run_operator_safety_gate(project_root=project_root)
    steps.append(safety_step)
    ok = ok and safety_step["ok"]
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

    if include_realistic_eval:
        if ok:
            if eval_root is not None:
                personal_eval_root = eval_root / "personal-memory-eval"
                personal_eval_root.mkdir(parents=True, exist_ok=True)
                personal_eval_step = _run_personal_memory_eval_gate(
                    project_root=project_root,
                    eval_root=personal_eval_root,
                )
            else:
                with TemporaryDirectory(prefix="memco-personal-memory-release-check-") as tmpdir:
                    personal_eval_step = _run_personal_memory_eval_gate(
                        project_root=project_root,
                        eval_root=Path(tmpdir),
                    )
        else:
            personal_eval_step = {
                "name": "personal_memory_eval_artifact",
                "ok": False,
                "skipped": True,
                "reason": "prior_gate_failed",
            }
        steps.append(personal_eval_step)
        ok = ok and personal_eval_step["ok"]

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

        live_smoke_requested = _live_smoke_requested() if include_live_smoke is None else include_live_smoke
        if live_smoke_requested:
            output_path = project_root / "var" / "reports" / "live-operator-smoke-current.json"
            if ok:
                with TemporaryDirectory(prefix="memco-live-operator-smoke-") as tmpdir:
                    live_smoke_step = _run_live_smoke_gate(
                        project_root=project_root,
                        database_url=postgres_database_url,
                        live_smoke_root=Path(tmpdir),
                        output_path=output_path,
                        live_smoke_required=False,
                    )
            else:
                live_smoke_step = {
                    "name": "live_operator_smoke",
                    "ok": False,
                    "skipped": True,
                    "reason": "prior_gate_failed",
                }
            steps.append(live_smoke_step)
            ok = ok and live_smoke_step["ok"]

    payload = {
        "artifact_type": "fixture_release_check"
        if fixture_ok
        else "canonical_postgres_release_check"
        if postgres_database_url
        else "repo_local_release_check",
        "ok": ok,
        "gate_type": "fixture-ok" if fixture_ok else "canonical-postgres" if postgres_database_url else "quick-repo-local",
        "fixture_only": fixture_ok,
        "release_eligible": False if fixture_ok else ok,
        "include_pytest": include_pytest,
        "include_eval": include_eval,
        "include_realistic_eval": include_realistic_eval,
        "include_postgres_smoke": bool(postgres_database_url),
        "project_root": str(project_root),
        "steps": steps,
    }
    result = attach_artifact_context(
        payload,
        project_root=project_root,
        steps=steps,
        live_smoke_requested=live_smoke_requested,
        live_smoke_required=False,
    )
    if fixture_ok:
        context = result.get("artifact_context") or {}
        context["runtime_mode"] = "fixture"
        context["runtime_provider"] = "mock"
        context["runtime_model"] = "fixture"
        context["fixture_only"] = True
        context["release_eligible"] = False
        if isinstance(context.get("config_source"), dict):
            context["config_source"]["checkout_release_eligible"] = False
            context["config_source"]["operator_release_eligible"] = False
        result["artifact_context"] = context
    return result


def run_strict_release_check(
    *,
    project_root: Path,
    eval_root: Path | None = None,
    postgres_database_url: str,
    postgres_root: Path | None = None,
    postgres_port: int | None = None,
    include_live_smoke: bool | None = None,
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
                include_live_smoke=include_live_smoke,
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
        include_live_smoke=include_live_smoke,
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
    live_smoke_requested = bool((release_artifact.get("artifact_context") or {}).get("live_smoke", {}).get("requested"))
    payload = {
        "artifact_type": "strict_quality_release_check",
        "ok": ok,
        "gate_type": "strict-quality",
        "base_gate_type": release_artifact["gate_type"],
        "benchmark_required": True,
        "include_postgres_smoke": True,
        "project_root": str(project_root),
        "steps": steps,
    }
    return attach_artifact_context(
        payload,
        project_root=project_root,
        steps=steps,
        live_smoke_requested=live_smoke_requested,
        live_smoke_required=False,
    )


def run_release_readiness_check(
    *,
    project_root: Path,
    eval_root: Path | None = None,
    postgres_database_url: str,
    postgres_root: Path | None = None,
    postgres_port: int | None = None,
) -> dict:
    if not postgres_database_url:
        raise ValueError("release-readiness-check requires postgres_database_url")
    if eval_root is None:
        with TemporaryDirectory(prefix="memco-release-readiness-check-") as tmpdir:
            return run_release_readiness_check(
                project_root=project_root,
                eval_root=Path(tmpdir),
                postgres_database_url=postgres_database_url,
                postgres_root=postgres_root,
                postgres_port=postgres_port,
            )

    release_artifact = run_strict_release_check(
        project_root=project_root,
        eval_root=eval_root,
        postgres_database_url=postgres_database_url,
        postgres_root=postgres_root,
        postgres_port=postgres_port,
        include_live_smoke=False,
    )
    steps = list(release_artifact["steps"])
    ok = release_artifact["ok"]
    live_smoke_requested = _live_smoke_requested()
    if not live_smoke_requested:
        live_smoke_step = {
            "name": "live_operator_smoke",
            "ok": False,
            "required": True,
            "skipped": True,
            "reason": "live_smoke_required_for_release_claim",
        }
    elif ok:
        output_path = project_root / "var" / "reports" / "live-operator-smoke-current.json"
        with TemporaryDirectory(prefix="memco-live-operator-smoke-") as tmpdir:
            live_smoke_step = _run_live_smoke_gate(
                project_root=project_root,
                database_url=postgres_database_url,
                live_smoke_root=Path(tmpdir),
                output_path=output_path,
                live_smoke_required=True,
            )
        live_smoke_step["required"] = True
    else:
        live_smoke_step = {
            "name": "live_operator_smoke",
            "ok": False,
            "required": True,
            "skipped": True,
            "reason": "prior_gate_failed",
        }
    steps.append(live_smoke_step)
    ok = ok and live_smoke_step["ok"]
    payload = {
        "artifact_type": "release_readiness_check",
        "ok": ok,
        "gate_type": "release-grade",
        "base_gate_type": release_artifact["gate_type"],
        "benchmark_required": True,
        "include_postgres_smoke": True,
        "live_smoke_required": True,
        "live_smoke_requested": live_smoke_requested,
        "project_root": str(project_root),
        "steps": steps,
    }
    return attach_artifact_context(
        payload,
        project_root=project_root,
        steps=steps,
        live_smoke_requested=live_smoke_requested,
        live_smoke_required=True,
    )


def _main() -> int:
    project_root = resolve_repo_project_root(Path(os.environ.get("MEMCO_PROJECT_ROOT", Path.cwd())).expanduser().resolve())
    postgres_database_url = os.environ.get("MEMCO_POSTGRES_DATABASE_URL", "").strip() or None
    output_path = os.environ.get("MEMCO_RELEASE_CHECK_OUTPUT", "").strip()
    strict_requested = os.environ.get("MEMCO_STRICT_RELEASE_CHECK", "").strip().lower() in {"1", "true", "yes", "on"}
    readiness_requested = os.environ.get("MEMCO_RELEASE_READINESS_CHECK", "").strip().lower() in {"1", "true", "yes", "on"}

    if readiness_requested:
        if not postgres_database_url:
            raise ValueError("MEMCO_POSTGRES_DATABASE_URL is required for MEMCO_RELEASE_READINESS_CHECK=1")
        result = run_release_readiness_check(
            project_root=project_root,
            postgres_database_url=postgres_database_url,
        )
    elif strict_requested:
        if not postgres_database_url:
            raise ValueError("MEMCO_POSTGRES_DATABASE_URL is required for MEMCO_STRICT_RELEASE_CHECK=1")
        result = run_strict_release_check(
            project_root=project_root,
            postgres_database_url=postgres_database_url,
        )
    else:
        result = run_release_check(
            project_root=project_root,
            include_eval=True,
            postgres_database_url=postgres_database_url,
        )

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if output_path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        result["artifact_path"] = str(path)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main())

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from memco.config import load_settings
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


def _run_eval_gate(*, eval_root: Path) -> dict:
    ensure_runtime(load_settings(eval_root))
    service = EvalService()
    service.seed_fixture_data(eval_root)
    artifact = service.run(eval_root)
    return {
        "name": "eval_artifact",
        "ok": artifact["failed"] == 0 and artifact["behavior_checks_total"] == artifact["behavior_checks_passed"],
        "root": str(eval_root),
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

    steps: list[dict] = []
    ok = True
    pytest_step: dict | None = None

    if include_pytest:
        pytest_step = _run_pytest_gate(project_root=project_root)
        steps.append(pytest_step)
        ok = pytest_step["ok"]

    if include_eval:
        if not include_pytest or (pytest_step is not None and pytest_step["ok"]):
            if eval_root is not None:
                eval_root.mkdir(parents=True, exist_ok=True)
                eval_step = _run_eval_gate(eval_root=eval_root)
            else:
                with TemporaryDirectory(prefix="memco-release-check-") as tmpdir:
                    eval_step = _run_eval_gate(eval_root=Path(tmpdir))
        else:
            eval_step = {
                "name": "eval_artifact",
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
        "artifact_type": "repo_local_release_check",
        "ok": ok,
        "include_pytest": include_pytest,
        "include_eval": include_eval,
        "include_postgres_smoke": bool(postgres_database_url),
        "project_root": str(project_root),
        "steps": steps,
    }

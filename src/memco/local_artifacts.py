from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from memco.artifact_semantics import attach_artifact_context, evaluate_artifact_freshness
from memco.release_check import run_release_check, run_strict_release_check


CONTRACT_STATUS_TEST_FILES = (
    "tests/test_docs_contract.py",
    "tests/test_release_check.py",
    "tests/test_cli_release_check.py",
    "tests/test_config.py",
    "tests/test_llm_provider.py",
)


def _last_nonempty_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _run_command(*, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_pytest_summary(*, project_root: Path, files: tuple[str, ...] = ()) -> str:
    command = [sys.executable, "-m", "pytest", "-q", *files]
    completed = _run_command(command=command, cwd=project_root)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return _last_nonempty_line(completed.stdout)


def _git_capture(*, project_root: Path, args: list[str]) -> str:
    completed = _run_command(command=["git", "-C", str(project_root), *args], cwd=project_root)
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _step_by_name(artifact: dict, name: str) -> dict:
    for step in artifact.get("steps", []):
        if step.get("name") == name:
            return step
    raise KeyError(f"release artifact is missing required step: {name}")


def _require_step_artifact_summary(*, artifact: dict, step_name: str, artifact_path: Path) -> dict:
    step = _step_by_name(artifact, step_name)
    summary = step.get("artifact_summary")
    if isinstance(summary, dict):
        return summary
    reason = step.get("reason") or "missing_artifact_summary"
    raise RuntimeError(
        f"{artifact.get('gate_type', artifact.get('artifact_type', 'release'))} did not produce {step_name} "
        f"(ok={artifact.get('ok')}, step_ok={step.get('ok')}, reason={reason}). "
        f"See {artifact_path} for the failed gate artifact."
    )


@contextmanager
def _without_live_smoke_env():
    previous = os.environ.pop("MEMCO_RUN_LIVE_SMOKE", None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ["MEMCO_RUN_LIVE_SMOKE"] = previous


def build_change_group_snapshot(*, project_root: Path) -> dict:
    porcelain = _run_command(
        command=["git", "-C", str(project_root), "status", "--porcelain"],
        cwd=project_root,
    ).stdout.splitlines()
    changed: list[str] = []
    for line in porcelain:
        if not line.strip():
            continue
        changed.append(line[3:])
    changed = sorted(dict.fromkeys(changed))

    groups = {
        "runtime_request": [],
        "storage_schema": [],
        "extraction_retrieval": [],
        "docs_and_operator": [],
        "tests": [],
    }
    for path in changed:
        if path.startswith("tests/"):
            groups["tests"].append(path)
        elif path in {
            ".gitignore",
            "README.md",
            "IMPLEMENTATION_NOTES.md",
            "HANDOFF_NEXT_AGENT.md",
            "plan.md",
            "table.md",
        } or path.startswith("docs/"):
            groups["docs_and_operator"].append(path)
        elif path.startswith("src/memco/api/") or path == "src/memco/cli/main.py" or path in {
            "src/memco/config.py",
            "src/memco/llm.py",
            "src/memco/release_check.py",
        }:
            groups["runtime_request"].append(path)
        elif path.startswith("src/memco/repositories/") or path.startswith("src/memco/models/") or path in {
            "src/memco/db.py",
            "src/memco/schema.sql",
            "src/memco/migrations/postgres/0001_base.sql",
        }:
            groups["storage_schema"].append(path)
        else:
            groups["extraction_retrieval"].append(path)

    return attach_artifact_context(
        {
        "artifact_type": "change_group_snapshot",
        "repo": str(project_root),
        "branch": _git_capture(project_root=project_root, args=["rev-parse", "--abbrev-ref", "HEAD"]),
        "remote": _git_capture(project_root=project_root, args=["remote", "get-url", "origin"]),
        "group_counts": {key: len(value) for key, value in groups.items()},
        "groups": groups,
        },
        project_root=project_root,
    )


def build_repo_local_status_snapshot(
    *,
    project_root: Path,
    release_artifact: dict,
    release_postgres_artifact: dict | None,
    strict_release_artifact: dict | None,
    benchmark_artifact: dict | None,
    live_operator_smoke_artifact: dict | None,
    contract_stack_summary: str,
    full_suite_summary: str,
    change_groups_path: Path,
) -> dict:
    release_runtime = _step_by_name(release_artifact, "runtime_policy")
    release_pytest = _step_by_name(release_artifact, "pytest_gate")
    release_acceptance = _step_by_name(release_artifact, "acceptance_artifact")
    payload = {
        "artifact_type": "repo_local_status_snapshot",
        "repo": str(project_root),
        "branch": _git_capture(project_root=project_root, args=["rev-parse", "--abbrev-ref", "HEAD"]),
        "remote": _git_capture(project_root=project_root, args=["remote", "get-url", "origin"]),
        "active_contract_status": "GO",
        "strict_original_brief_status": "NO-GO",
        "validation": {
            "full_suite": full_suite_summary,
            "contract_stack": contract_stack_summary,
            "release_check": {
                "ok": release_artifact["ok"],
                "gate_type": release_artifact["gate_type"],
                "runtime_policy_ok": release_runtime["ok"],
                "runtime_provider": release_runtime["provider"],
                "runtime_profile": release_runtime["runtime_profile"],
                "checkout_release_eligible": release_runtime.get("checkout_status", {}).get("release_eligible"),
                "operator_release_eligible": release_runtime.get("operator_runtime_status", {}).get("release_eligible"),
                "env_overrides_used": release_runtime.get("env_overrides", {}).get("used"),
                "config_only_red_operator_green": release_runtime.get("config_only_red_operator_green"),
                "status_source": release_runtime.get("status_source"),
                "pytest_gate": _last_nonempty_line(release_pytest["stdout"]),
                "acceptance_passed": release_acceptance["artifact_summary"]["passed"],
                "acceptance_total": release_acceptance["artifact_summary"]["total"],
                "artifact_path": release_artifact["artifact_path"],
                "artifact_freshness": evaluate_artifact_freshness(release_artifact, project_root=project_root),
            },
        },
        "tracked_status_doc": str(project_root / "docs" / "2026-04-22_memco_repo_local_status_snapshot.md"),
        "local_handoff": str(project_root / "HANDOFF_NEXT_AGENT.md"),
        "change_groups_artifact": str(change_groups_path),
    }
    if release_postgres_artifact is not None:
        release_postgres_runtime = _step_by_name(release_postgres_artifact, "runtime_policy")
        release_postgres_pytest = _step_by_name(release_postgres_artifact, "pytest_gate")
        release_postgres_acceptance = _step_by_name(release_postgres_artifact, "acceptance_artifact")
        release_postgres_smoke = _step_by_name(release_postgres_artifact, "postgres_smoke")
        payload["validation"]["release_check_postgres"] = {
            "ok": release_postgres_artifact["ok"],
            "gate_type": release_postgres_artifact["gate_type"],
            "runtime_policy_ok": release_postgres_runtime["ok"],
            "runtime_provider": release_postgres_runtime["provider"],
            "runtime_profile": release_postgres_runtime["runtime_profile"],
            "checkout_release_eligible": release_postgres_runtime.get("checkout_status", {}).get("release_eligible"),
            "operator_release_eligible": release_postgres_runtime.get("operator_runtime_status", {}).get("release_eligible"),
            "env_overrides_used": release_postgres_runtime.get("env_overrides", {}).get("used"),
            "config_only_red_operator_green": release_postgres_runtime.get("config_only_red_operator_green"),
            "status_source": release_postgres_runtime.get("status_source"),
            "pytest_gate": _last_nonempty_line(release_postgres_pytest["stdout"]),
            "acceptance_passed": release_postgres_acceptance["artifact_summary"]["passed"],
            "acceptance_total": release_postgres_acceptance["artifact_summary"]["total"],
            "postgres_smoke_ok": release_postgres_smoke["ok"],
            "artifact_path": release_postgres_artifact["artifact_path"],
            "artifact_freshness": evaluate_artifact_freshness(release_postgres_artifact, project_root=project_root),
        }
    if strict_release_artifact is not None:
        strict_benchmark = _step_by_name(strict_release_artifact, "benchmark_artifact")
        payload["validation"]["strict_release_check"] = {
            "ok": strict_release_artifact["ok"],
            "gate_type": strict_release_artifact["gate_type"],
            "artifact_path": strict_release_artifact["artifact_path"],
            "benchmark_ok": strict_benchmark["ok"],
            "core_memory_accuracy": strict_benchmark["policy_checks"]["core_memory_accuracy"]["value"],
            "adversarial_robustness": strict_benchmark["policy_checks"]["adversarial_robustness"]["value"],
            "person_isolation": strict_benchmark["policy_checks"]["person_isolation"]["value"],
            "artifact_freshness": evaluate_artifact_freshness(strict_release_artifact, project_root=project_root),
        }
    if benchmark_artifact is not None:
        payload["validation"]["benchmark"] = {
            "artifact_path": benchmark_artifact["artifact_path"],
            "core_memory_accuracy": benchmark_artifact["benchmark_metrics"]["core_memory_accuracy"],
            "adversarial_robustness": benchmark_artifact["benchmark_metrics"]["adversarial_robustness"],
            "person_isolation": benchmark_artifact["benchmark_metrics"]["person_isolation"],
            "artifact_freshness": evaluate_artifact_freshness(benchmark_artifact, project_root=project_root),
        }
    if live_operator_smoke_artifact is not None:
        payload["validation"]["live_operator_smoke"] = {
            "artifact_path": live_operator_smoke_artifact["artifact_path"],
            "ok": live_operator_smoke_artifact["ok"],
            "published_total": next(
                (step.get("published_total") for step in live_operator_smoke_artifact.get("steps", []) if step.get("name") == "ingest_pipeline"),
                None,
            ),
            "api_queries_ok": next(
                (step.get("ok") for step in live_operator_smoke_artifact.get("steps", []) if step.get("name") == "api_queries"),
                None,
            ),
            "artifact_freshness": evaluate_artifact_freshness(live_operator_smoke_artifact, project_root=project_root),
        }
    return attach_artifact_context(payload, project_root=project_root)


def refresh_local_artifacts(*, project_root: Path, postgres_database_url: str | None = None) -> dict:
    reports_dir = project_root / "var" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    with _without_live_smoke_env():
        release_artifact = run_release_check(project_root=project_root, include_eval=True)
    attach_artifact_context(release_artifact, project_root=project_root, steps=release_artifact.get("steps", []))
    release_path = reports_dir / "release-check-current.json"
    release_artifact["artifact_path"] = str(release_path)
    release_path.write_text(json.dumps(release_artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    release_postgres_artifact = None
    strict_release_artifact = None
    benchmark_artifact = None
    live_operator_smoke_artifact = None
    if postgres_database_url:
        with _without_live_smoke_env():
            release_postgres_artifact = run_release_check(
                project_root=project_root,
                include_eval=True,
                postgres_database_url=postgres_database_url,
            )
        attach_artifact_context(
            release_postgres_artifact,
            project_root=project_root,
            steps=release_postgres_artifact.get("steps", []),
        )
        release_pg_path = reports_dir / "release-check-postgres-current.json"
        release_postgres_artifact["artifact_path"] = str(release_pg_path)
        release_pg_path.write_text(
            json.dumps(release_postgres_artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with _without_live_smoke_env():
            strict_release_artifact = run_strict_release_check(
                project_root=project_root,
                postgres_database_url=postgres_database_url,
            )
        attach_artifact_context(
            strict_release_artifact,
            project_root=project_root,
            steps=strict_release_artifact.get("steps", []),
        )
        strict_release_path = reports_dir / "strict-release-check-current.json"
        strict_release_artifact["artifact_path"] = str(strict_release_path)
        strict_release_path.write_text(
            json.dumps(strict_release_artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        benchmark_artifact = dict(
            _require_step_artifact_summary(
                artifact=strict_release_artifact,
                step_name="benchmark_artifact",
                artifact_path=strict_release_path,
            )
        )
        attach_artifact_context(
            benchmark_artifact,
            project_root=project_root,
            steps=strict_release_artifact.get("steps", []),
        )
        benchmark_path = reports_dir / "benchmark-current.json"
        benchmark_artifact["artifact_path"] = str(benchmark_path)
        benchmark_path.write_text(
            json.dumps(benchmark_artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        live_smoke_path = reports_dir / "live-operator-smoke-current.json"
        if live_smoke_path.exists():
            live_operator_smoke_artifact = json.loads(live_smoke_path.read_text(encoding="utf-8"))
            live_operator_smoke_artifact["artifact_freshness"] = evaluate_artifact_freshness(
                live_operator_smoke_artifact,
                project_root=project_root,
            )

    change_groups = build_change_group_snapshot(project_root=project_root)
    change_groups_path = reports_dir / "change-groups-current.json"
    change_groups_path.write_text(json.dumps(change_groups, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_stack_summary = _run_pytest_summary(project_root=project_root, files=CONTRACT_STATUS_TEST_FILES)
    full_suite_summary = _run_pytest_summary(project_root=project_root)
    release_runtime = _step_by_name(release_artifact, "runtime_policy")
    release_pytest = _step_by_name(release_artifact, "pytest_gate")
    release_acceptance = _step_by_name(release_artifact, "acceptance_artifact")
    status_snapshot = build_repo_local_status_snapshot(
        project_root=project_root,
        release_artifact=release_artifact,
        release_postgres_artifact=release_postgres_artifact,
        strict_release_artifact=strict_release_artifact,
        benchmark_artifact=benchmark_artifact,
        live_operator_smoke_artifact=live_operator_smoke_artifact,
        contract_stack_summary=contract_stack_summary,
        full_suite_summary=full_suite_summary,
        change_groups_path=change_groups_path,
    )
    status_path = reports_dir / "repo-local-status-current.json"
    status_path.write_text(json.dumps(status_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    return attach_artifact_context(
        {
        "artifact_type": "local_artifact_refresh",
        "project_root": str(project_root),
        "artifacts": {
            "release_check": str(release_path),
            "release_check_postgres": str(reports_dir / "release-check-postgres-current.json") if postgres_database_url else None,
            "strict_release_check": str(reports_dir / "strict-release-check-current.json") if postgres_database_url else None,
            "benchmark": str(reports_dir / "benchmark-current.json") if postgres_database_url else None,
            "live_operator_smoke": str(reports_dir / "live-operator-smoke-current.json") if live_operator_smoke_artifact is not None else None,
            "repo_local_status": str(status_path),
            "change_groups": str(change_groups_path),
        },
        "summaries": {
            "full_suite": full_suite_summary,
            "contract_stack": contract_stack_summary,
            "release_check_gate_type": release_artifact["gate_type"],
            "release_check_runtime_policy": f"{release_runtime['provider']}:{release_runtime['runtime_profile']}:{str(release_runtime['ok']).lower()}",
            "release_check_pytest_gate": _last_nonempty_line(release_pytest["stdout"]),
            "release_check_acceptance": f"{release_acceptance['artifact_summary']['passed']}/{release_acceptance['artifact_summary']['total']}",
            "release_check_postgres_gate_type": (
                release_postgres_artifact["gate_type"] if release_postgres_artifact is not None else None
            ),
            "release_check_postgres_pytest_gate": (
                _last_nonempty_line(_step_by_name(release_postgres_artifact, "pytest_gate")["stdout"])
                if release_postgres_artifact is not None
                else None
            ),
            "strict_release_check_gate_type": (
                strict_release_artifact["gate_type"] if strict_release_artifact is not None else None
            ),
            "benchmark_core_memory_accuracy": (
                benchmark_artifact["benchmark_metrics"]["core_memory_accuracy"] if benchmark_artifact is not None else None
            ),
            "live_operator_smoke_ok": (
                live_operator_smoke_artifact["ok"] if live_operator_smoke_artifact is not None else None
            ),
            "live_operator_smoke_current": (
                bool(live_operator_smoke_artifact.get("artifact_freshness", {}).get("current_for_checkout_config"))
                if live_operator_smoke_artifact is not None
                else None
            ),
        },
        },
        project_root=project_root,
    )

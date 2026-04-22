from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memco.release_check import run_release_check


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


def build_change_group_snapshot(*, project_root: Path) -> dict:
    porcelain = _git_capture(project_root=project_root, args=["status", "--porcelain"]).splitlines()
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

    return {
        "artifact_type": "change_group_snapshot",
        "repo": str(project_root),
        "branch": _git_capture(project_root=project_root, args=["rev-parse", "--abbrev-ref", "HEAD"]),
        "remote": _git_capture(project_root=project_root, args=["remote", "get-url", "origin"]),
        "group_counts": {key: len(value) for key, value in groups.items()},
        "groups": groups,
    }


def build_repo_local_status_snapshot(
    *,
    project_root: Path,
    release_artifact: dict,
    release_postgres_artifact: dict | None,
    contract_stack_summary: str,
    full_suite_summary: str,
    change_groups_path: Path,
) -> dict:
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
                "pytest_gate": _last_nonempty_line(release_artifact["steps"][0]["stdout"]),
                "acceptance_passed": release_artifact["steps"][1]["artifact_summary"]["passed"],
                "acceptance_total": release_artifact["steps"][1]["artifact_summary"]["total"],
                "artifact_path": release_artifact["artifact_path"],
            },
        },
        "tracked_status_doc": str(project_root / "docs" / "2026-04-22_memco_repo_local_status_snapshot.md"),
        "local_handoff": str(project_root / "HANDOFF_NEXT_AGENT.md"),
        "change_groups_artifact": str(change_groups_path),
    }
    if release_postgres_artifact is not None:
        payload["validation"]["release_check_postgres"] = {
            "ok": release_postgres_artifact["ok"],
            "pytest_gate": _last_nonempty_line(release_postgres_artifact["steps"][0]["stdout"]),
            "acceptance_passed": release_postgres_artifact["steps"][1]["artifact_summary"]["passed"],
            "acceptance_total": release_postgres_artifact["steps"][1]["artifact_summary"]["total"],
            "postgres_smoke_ok": release_postgres_artifact["steps"][2]["ok"],
            "artifact_path": release_postgres_artifact["artifact_path"],
        }
    return payload


def refresh_local_artifacts(*, project_root: Path, postgres_database_url: str | None = None) -> dict:
    reports_dir = project_root / "var" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    release_artifact = run_release_check(project_root=project_root, include_eval=True)
    release_path = reports_dir / "release-check-current.json"
    release_artifact["artifact_path"] = str(release_path)
    release_path.write_text(json.dumps(release_artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    release_postgres_artifact = None
    if postgres_database_url:
        release_postgres_artifact = run_release_check(
            project_root=project_root,
            include_eval=True,
            postgres_database_url=postgres_database_url,
        )
        release_pg_path = reports_dir / "release-check-postgres-current.json"
        release_postgres_artifact["artifact_path"] = str(release_pg_path)
        release_pg_path.write_text(
            json.dumps(release_postgres_artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    change_groups = build_change_group_snapshot(project_root=project_root)
    change_groups_path = reports_dir / "change-groups-current.json"
    change_groups_path.write_text(json.dumps(change_groups, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_stack_summary = _run_pytest_summary(project_root=project_root, files=CONTRACT_STATUS_TEST_FILES)
    full_suite_summary = _run_pytest_summary(project_root=project_root)
    status_snapshot = build_repo_local_status_snapshot(
        project_root=project_root,
        release_artifact=release_artifact,
        release_postgres_artifact=release_postgres_artifact,
        contract_stack_summary=contract_stack_summary,
        full_suite_summary=full_suite_summary,
        change_groups_path=change_groups_path,
    )
    status_path = reports_dir / "repo-local-status-current.json"
    status_path.write_text(json.dumps(status_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "artifact_type": "local_artifact_refresh",
        "project_root": str(project_root),
        "artifacts": {
            "release_check": str(release_path),
            "release_check_postgres": str(reports_dir / "release-check-postgres-current.json") if postgres_database_url else None,
            "repo_local_status": str(status_path),
            "change_groups": str(change_groups_path),
        },
        "summaries": {
            "full_suite": full_suite_summary,
            "contract_stack": contract_stack_summary,
            "release_check_pytest_gate": _last_nonempty_line(release_artifact["steps"][0]["stdout"]),
            "release_check_acceptance": f"{release_artifact['steps'][1]['artifact_summary']['passed']}/{release_artifact['steps'][1]['artifact_summary']['total']}",
            "release_check_postgres_pytest_gate": (
                _last_nonempty_line(release_postgres_artifact["steps"][0]["stdout"])
                if release_postgres_artifact is not None
                else None
            ),
        },
    }

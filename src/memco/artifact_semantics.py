from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from subprocess import run as _subprocess_run
from typing import Any

from memco.config import load_settings
from memco.llm import llm_runtime_status


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str | None:
    if path.is_symlink():
        return _sha256_text(f"symlink:{path.readlink()}")
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_capture(*, project_root: Path, args: list[str]) -> str:
    completed = _subprocess_run(
        ["git", "-C", str(project_root), *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _worktree_sha256(project_root: Path, *, status: str) -> str:
    digest = hashlib.sha256()
    digest.update(status.encode("utf-8"))
    tracked_diff = _git_capture(project_root=project_root, args=["diff", "--no-ext-diff", "--binary", "HEAD", "--"])
    digest.update(b"\n--tracked-diff--\n")
    digest.update(tracked_diff.encode("utf-8", errors="replace"))
    cached_diff = _git_capture(
        project_root=project_root,
        args=["diff", "--cached", "--no-ext-diff", "--binary", "HEAD", "--"],
    )
    digest.update(b"\n--cached-diff--\n")
    digest.update(cached_diff.encode("utf-8", errors="replace"))
    untracked = _git_capture(project_root=project_root, args=["ls-files", "-o", "--exclude-standard"])
    digest.update(b"\n--untracked--\n")
    for rel_path in sorted(line for line in untracked.splitlines() if line.strip()):
        path = project_root / rel_path
        digest.update(rel_path.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(_file_sha256(path)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _checkout_state(project_root: Path) -> dict[str, Any]:
    status = _git_capture(project_root=project_root, args=["status", "--porcelain=v1"])
    status_lines = [line for line in status.splitlines() if line.strip()]
    return {
        "git_head": _git_capture(project_root=project_root, args=["rev-parse", "HEAD"]),
        "git_branch": _git_capture(project_root=project_root, args=["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(status_lines),
        "dirty_count": len(status_lines),
        "status_sha256": _sha256_text(status),
        "worktree_sha256": _worktree_sha256(project_root, status=status),
    }


def _find_step(steps: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for step in steps:
        if step.get("name") == name:
            return step
    return None


def build_artifact_context(
    *,
    project_root: Path,
    steps: list[dict[str, Any]] | None = None,
    live_smoke_requested: bool = False,
    live_smoke_required: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated = generated_at or _utc_now()
    settings = load_settings(project_root)
    runtime_status = llm_runtime_status(settings)
    operator_status = runtime_status["operator_runtime_status"]
    checkout_status = runtime_status["checkout_status"]
    config_path = settings.config_path
    checked_steps = steps or []
    live_smoke_step = _find_step(checked_steps, "live_operator_smoke")
    return {
        "schema_version": 1,
        "generated_at": generated,
        "project_root": str(project_root),
        "runtime_mode": operator_status["runtime_profile"],
        "runtime_provider": operator_status["provider"],
        "runtime_model": operator_status["model"],
        "status_source": runtime_status["status_source"],
        "config_source": {
            "path": str(config_path),
            "exists": config_path.exists(),
            "sha256": _file_sha256(config_path),
            "env_applied": True,
            "checkout_release_eligible": checkout_status["release_eligible"],
            "operator_release_eligible": operator_status["release_eligible"],
            "config_only_red_operator_green": runtime_status["config_only_red_operator_green"],
        },
        "env_overrides": runtime_status["env_overrides"],
        "live_smoke": {
            "required": live_smoke_required,
            "requested": live_smoke_requested,
            "ran": bool(live_smoke_step and not live_smoke_step.get("skipped")),
            "ok": live_smoke_step.get("ok") if live_smoke_step else None,
            "skipped": bool(live_smoke_step.get("skipped")) if live_smoke_step else not live_smoke_requested,
            "reason": live_smoke_step.get("reason") if live_smoke_step else None,
            "artifact_path": live_smoke_step.get("artifact_path") if live_smoke_step else None,
        },
        "checkout": _checkout_state(project_root),
        "freshness": {
            "status": "current_at_generation",
            "stale_relative_to_current_checkout": False,
            "stale_relative_to_current_config": False,
        },
    }


def attach_artifact_context(
    payload: dict[str, Any],
    *,
    project_root: Path,
    steps: list[dict[str, Any]] | None = None,
    live_smoke_requested: bool = False,
    live_smoke_required: bool = False,
) -> dict[str, Any]:
    generated_at = str(payload.get("generated_at") or _utc_now())
    selected_steps = steps if steps is not None else list(payload.get("steps", []))
    payload["generated_at"] = generated_at
    payload["artifact_context"] = build_artifact_context(
        project_root=project_root,
        steps=selected_steps,
        live_smoke_requested=live_smoke_requested,
        live_smoke_required=live_smoke_required,
        generated_at=generated_at,
    )
    return payload


def evaluate_artifact_freshness(payload: dict[str, Any], *, project_root: Path) -> dict[str, Any]:
    context = payload.get("artifact_context")
    if not isinstance(context, dict):
        return {
            "status": "unknown_legacy_artifact",
            "current_for_checkout_config": False,
            "stale_relative_to_current_checkout": None,
            "stale_relative_to_current_config": None,
            "reason": "artifact_missing_context",
        }

    current = build_artifact_context(project_root=project_root)
    artifact_checkout = context.get("checkout") or {}
    artifact_config = context.get("config_source") or {}
    current_checkout = current["checkout"]
    current_config = current["config_source"]
    artifact_env = context.get("env_overrides") or {}
    current_env = current["env_overrides"]
    stale_checkout = artifact_checkout.get("git_head") != current_checkout.get("git_head")
    stale_checkout = stale_checkout or artifact_checkout.get("status_sha256") != current_checkout.get("status_sha256")
    if artifact_checkout.get("worktree_sha256") is not None or current_checkout.get("worktree_sha256") is not None:
        stale_checkout = stale_checkout or artifact_checkout.get("worktree_sha256") != current_checkout.get("worktree_sha256")
    stale_config = artifact_config.get("sha256") != current_config.get("sha256")
    stale_env = context.get("status_source") != current.get("status_source") or artifact_env != current_env
    is_current = not stale_checkout and not stale_config and not stale_env
    return {
        "status": "current" if is_current else "stale",
        "current_for_checkout_config": is_current,
        "stale_relative_to_current_checkout": stale_checkout,
        "stale_relative_to_current_config": stale_config,
        "stale_relative_to_current_env": stale_env,
        "artifact_generated_at": context.get("generated_at"),
        "current_evaluated_at": current["generated_at"],
        "artifact_git_head": artifact_checkout.get("git_head"),
        "current_git_head": current_checkout.get("git_head"),
        "artifact_worktree_sha256": artifact_checkout.get("worktree_sha256"),
        "current_worktree_sha256": current_checkout.get("worktree_sha256"),
        "artifact_config_sha256": artifact_config.get("sha256"),
        "current_config_sha256": current_config.get("sha256"),
        "artifact_status_source": context.get("status_source"),
        "current_status_source": current.get("status_source"),
    }

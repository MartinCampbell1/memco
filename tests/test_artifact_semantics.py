from __future__ import annotations

from subprocess import run

from memco.artifact_semantics import build_artifact_context, evaluate_artifact_freshness
from memco.config import Settings, write_settings


def test_evaluate_artifact_freshness_marks_current_and_stale_artifacts(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    write_settings(settings)
    context = build_artifact_context(project_root=project_root)

    current = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)
    assert current["status"] == "current"
    assert current["current_for_checkout_config"] is True

    stale_checkout_context = {
        **context,
        "checkout": {
            **context["checkout"],
            "status_sha256": "old-checkout-status",
        },
    }
    stale_checkout = evaluate_artifact_freshness(
        {"artifact_context": stale_checkout_context},
        project_root=project_root,
    )
    assert stale_checkout["status"] == "stale"
    assert stale_checkout["current_for_checkout_config"] is False
    assert stale_checkout["stale_relative_to_current_checkout"] is True

    stale_config_context = {
        **context,
        "config_source": {
            **context["config_source"],
            "sha256": "old-config-sha",
        },
    }
    stale_config = evaluate_artifact_freshness(
        {"artifact_context": stale_config_context},
        project_root=project_root,
    )
    assert stale_config["status"] == "stale"
    assert stale_config["current_for_checkout_config"] is False
    assert stale_config["stale_relative_to_current_config"] is True

    stale_env_context = {
        **context,
        "status_source": "env-injected",
        "env_overrides": {
            "used": True,
            "present_keys": ["MEMCO_LLM_API_KEY"],
            "live_credentials_present": True,
            "live_credential_keys": ["MEMCO_LLM_API_KEY"],
        },
    }
    stale_env = evaluate_artifact_freshness(
        {"artifact_context": stale_env_context},
        project_root=project_root,
    )
    assert stale_env["status"] == "stale"
    assert stale_env["current_for_checkout_config"] is False
    assert stale_env["stale_relative_to_current_env"] is True


def test_evaluate_artifact_freshness_marks_legacy_artifact_unknown(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    write_settings(settings)

    result = evaluate_artifact_freshness({}, project_root=project_root)

    assert result["status"] == "unknown_legacy_artifact"
    assert result["current_for_checkout_config"] is False
    assert result["reason"] == "artifact_missing_context"


def test_evaluate_artifact_freshness_detects_content_change_with_same_status_line(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
    (project_root / ".gitignore").write_text("var/\n", encoding="utf-8")
    tracked = project_root / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    run(["git", "add", ".gitignore", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)
    run(
        [
            "git",
            "-c",
            "user.name=Memco Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    settings = Settings(root=project_root)
    write_settings(settings)

    tracked.write_text("first dirty content\n", encoding="utf-8")
    context = build_artifact_context(project_root=project_root)
    tracked.write_text("second dirty content\n", encoding="utf-8")

    current_context = build_artifact_context(project_root=project_root)
    assert context["checkout"]["status_sha256"] == current_context["checkout"]["status_sha256"]
    assert context["checkout"]["worktree_sha256"] != current_context["checkout"]["worktree_sha256"]

    result = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)

    assert result["status"] == "stale"
    assert result["current_for_checkout_config"] is False
    assert result["stale_relative_to_current_checkout"] is True


def test_evaluate_artifact_freshness_detects_staged_content_change_with_same_status_line(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
    (project_root / ".gitignore").write_text("var/\n", encoding="utf-8")
    tracked = project_root / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    run(["git", "add", ".gitignore", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)
    run(
        [
            "git",
            "-c",
            "user.name=Memco Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    settings = Settings(root=project_root)
    write_settings(settings)

    tracked.write_text("first staged content\n", encoding="utf-8")
    run(["git", "add", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)
    context = build_artifact_context(project_root=project_root)
    tracked.write_text("second staged content\n", encoding="utf-8")
    run(["git", "add", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)

    current_context = build_artifact_context(project_root=project_root)
    assert context["checkout"]["status_sha256"] == current_context["checkout"]["status_sha256"]
    assert context["checkout"]["worktree_sha256"] != current_context["checkout"]["worktree_sha256"]

    result = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)

    assert result["status"] == "stale"
    assert result["current_for_checkout_config"] is False
    assert result["stale_relative_to_current_checkout"] is True


def test_evaluate_artifact_freshness_detects_index_content_change_with_same_worktree(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
    (project_root / ".gitignore").write_text("var/\n", encoding="utf-8")
    tracked = project_root / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    run(["git", "add", ".gitignore", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)
    run(
        [
            "git",
            "-c",
            "user.name=Memco Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    settings = Settings(root=project_root)
    write_settings(settings)

    tracked.write_text("first staged content\n", encoding="utf-8")
    run(["git", "add", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)
    tracked.write_text("same worktree content\n", encoding="utf-8")
    context = build_artifact_context(project_root=project_root)

    tracked.write_text("second staged content\n", encoding="utf-8")
    run(["git", "add", "tracked.txt"], cwd=project_root, check=True, capture_output=True, text=True)
    tracked.write_text("same worktree content\n", encoding="utf-8")
    current_context = build_artifact_context(project_root=project_root)

    assert context["checkout"]["status_sha256"] == current_context["checkout"]["status_sha256"]
    assert context["checkout"]["worktree_sha256"] != current_context["checkout"]["worktree_sha256"]

    result = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)

    assert result["status"] == "stale"
    assert result["current_for_checkout_config"] is False
    assert result["stale_relative_to_current_checkout"] is True


def test_evaluate_artifact_freshness_detects_untracked_content_change(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
    (project_root / ".gitignore").write_text("var/\n", encoding="utf-8")
    run(["git", "add", ".gitignore"], cwd=project_root, check=True, capture_output=True, text=True)
    run(
        [
            "git",
            "-c",
            "user.name=Memco Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    settings = Settings(root=project_root)
    write_settings(settings)
    scratch = project_root / "scratch.bin"

    scratch.write_bytes(b"first-content")
    context = build_artifact_context(project_root=project_root)
    scratch.write_bytes(b"second-content")

    current_context = build_artifact_context(project_root=project_root)
    assert context["checkout"]["status_sha256"] == current_context["checkout"]["status_sha256"]
    assert context["checkout"]["worktree_sha256"] != current_context["checkout"]["worktree_sha256"]

    result = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)

    assert result["status"] == "stale"
    assert result["current_for_checkout_config"] is False
    assert result["stale_relative_to_current_checkout"] is True


def test_evaluate_artifact_freshness_ignores_ignored_runtime_artifact_changes(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
    (project_root / ".gitignore").write_text("var/\n", encoding="utf-8")
    run(["git", "add", ".gitignore"], cwd=project_root, check=True, capture_output=True, text=True)
    run(
        [
            "git",
            "-c",
            "user.name=Memco Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    settings = Settings(root=project_root)
    write_settings(settings)
    report = project_root / "var" / "reports" / "release-check-current.json"
    report.parent.mkdir(parents=True)

    report.write_text('{"ok": true}\n', encoding="utf-8")
    context = build_artifact_context(project_root=project_root)
    report.write_text('{"ok": false}\n', encoding="utf-8")

    current_context = build_artifact_context(project_root=project_root)
    assert context["checkout"]["status_sha256"] == current_context["checkout"]["status_sha256"]
    assert context["checkout"]["worktree_sha256"] == current_context["checkout"]["worktree_sha256"]

    result = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)

    assert result["status"] == "current"
    assert result["current_for_checkout_config"] is True
    assert result["stale_relative_to_current_checkout"] is False


def test_evaluate_artifact_freshness_hashes_untracked_symlink_target_not_external_content(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    external = tmp_path / "external-secret.txt"
    external.write_text("first external content\n", encoding="utf-8")
    run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
    (project_root / ".gitignore").write_text("var/\n", encoding="utf-8")
    run(["git", "add", ".gitignore"], cwd=project_root, check=True, capture_output=True, text=True)
    run(
        [
            "git",
            "-c",
            "user.name=Memco Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    settings = Settings(root=project_root)
    write_settings(settings)
    (project_root / "external-link.txt").symlink_to(external)

    context = build_artifact_context(project_root=project_root)
    external.write_text("second external content\n", encoding="utf-8")

    current_context = build_artifact_context(project_root=project_root)
    assert context["checkout"]["status_sha256"] == current_context["checkout"]["status_sha256"]
    assert context["checkout"]["worktree_sha256"] == current_context["checkout"]["worktree_sha256"]

    result = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)

    assert result["status"] == "current"
    assert result["current_for_checkout_config"] is True

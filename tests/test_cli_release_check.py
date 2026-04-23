from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _seed_repo_root(path: Path) -> Path:
    (path / "src" / "memco").mkdir(parents=True, exist_ok=True)
    (path / "tests").mkdir(exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname='memco'\n", encoding="utf-8")
    (path / "README.md").write_text("# Memco\n", encoding="utf-8")
    return path


def test_cli_release_check_wraps_runner(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_release_check(
        *,
        project_root: Path,
        eval_root: Path | None,
        include_eval: bool,
        postgres_database_url: str | None,
        postgres_root: Path | None,
        postgres_port: int | None,
    ):
        captured["project_root"] = project_root
        captured["eval_root"] = eval_root
        captured["include_eval"] = include_eval
        captured["postgres_database_url"] = postgres_database_url
        captured["postgres_root"] = postgres_root
        captured["postgres_port"] = postgres_port
        return {
            "artifact_type": "repo_local_release_check",
            "ok": True,
            "steps": [{"name": "pytest_gate", "ok": True}],
        }

    monkeypatch.setattr("memco.cli.main.run_release_check", fake_run_release_check)
    runtime_root = tmp_path / "release-runtime"
    result = runner.invoke(
        command,
        ["release-check", "--root", str(runtime_root)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["artifact_type"] == "repo_local_release_check"
    assert captured["project_root"] == Path.cwd().resolve()
    assert captured["eval_root"] == runtime_root.resolve()
    assert captured["include_eval"] is True
    assert captured["postgres_database_url"] is None
    assert captured["postgres_root"] is None
    assert captured["postgres_port"] is None


def test_cli_release_check_passes_optional_postgres_smoke(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_release_check(
        *,
        project_root: Path,
        eval_root: Path | None,
        include_eval: bool,
        postgres_database_url: str | None,
        postgres_root: Path | None,
        postgres_port: int | None,
    ):
        captured["postgres_database_url"] = postgres_database_url
        captured["postgres_root"] = postgres_root
        captured["postgres_port"] = postgres_port
        return {
            "artifact_type": "repo_local_release_check",
            "ok": True,
            "steps": [{"name": "postgres_smoke", "ok": True}],
        }

    monkeypatch.setattr("memco.cli.main.run_release_check", fake_run_release_check)
    runtime_root = tmp_path / "release-runtime"
    result = runner.invoke(
        command,
        [
            "release-check",
            "--root",
            str(runtime_root),
            "--postgres-database-url",
            "postgresql://example/postgres",
            "--postgres-port",
            "8789",
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert captured["postgres_database_url"] == "postgresql://example/postgres"
    assert captured["postgres_root"] == runtime_root.resolve().parent / f"{runtime_root.resolve().name}-postgres-smoke"
    assert captured["postgres_port"] == 8789


def test_cli_release_check_can_write_artifact_file(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    output_path = tmp_path / "artifacts" / "release-check.json"

    monkeypatch.setattr(
        "memco.cli.main.run_release_check",
        lambda **kwargs: {
            "artifact_type": "repo_local_release_check",
            "ok": True,
            "steps": [{"name": "pytest_gate", "ok": True}],
        },
    )
    result = runner.invoke(
        command,
        ["release-check", "--output", str(output_path)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_path"] == str(output_path.resolve())
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == payload


def test_cli_release_check_supports_explicit_project_root(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}
    repo_root = _seed_repo_root(tmp_path)

    def fake_run_release_check(
        *,
        project_root: Path,
        eval_root: Path | None,
        include_eval: bool,
        postgres_database_url: str | None,
        postgres_root: Path | None,
        postgres_port: int | None,
    ):
        captured["project_root"] = project_root
        return {
            "artifact_type": "repo_local_release_check",
            "ok": True,
            "steps": [{"name": "pytest_gate", "ok": True}],
        }

    monkeypatch.setattr("memco.cli.main.run_release_check", fake_run_release_check)
    result = runner.invoke(
        command,
        ["release-check", "--project-root", str(repo_root)],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    assert captured["project_root"] == repo_root.resolve()


def test_cli_release_check_returns_nonzero_on_failure(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()

    monkeypatch.setattr(
        "memco.cli.main.run_release_check",
        lambda **kwargs: {
            "artifact_type": "repo_local_release_check",
            "ok": False,
            "steps": [{"name": "pytest_gate", "ok": False}],
        },
    )
    result = runner.invoke(
        command,
        ["release-check"],
        prog_name="memco",
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False


def test_cli_strict_release_check_wraps_runner(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_strict_release_check(
        *,
        project_root: Path,
        eval_root: Path | None,
        postgres_database_url: str,
        postgres_root: Path | None,
        postgres_port: int | None,
    ):
        captured["project_root"] = project_root
        captured["eval_root"] = eval_root
        captured["postgres_database_url"] = postgres_database_url
        captured["postgres_root"] = postgres_root
        captured["postgres_port"] = postgres_port
        return {
            "artifact_type": "strict_quality_release_check",
            "ok": True,
            "steps": [{"name": "benchmark_artifact", "ok": True}],
        }

    monkeypatch.setattr("memco.cli.main.run_strict_release_check", fake_run_strict_release_check)
    runtime_root = tmp_path / "strict-release-runtime"
    result = runner.invoke(
        command,
        [
            "strict-release-check",
            "--root",
            str(runtime_root),
            "--postgres-database-url",
            "postgresql://example/postgres",
            "--postgres-port",
            "8790",
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "strict_quality_release_check"
    assert payload["ok"] is True
    assert captured["project_root"] == Path.cwd().resolve()
    assert captured["eval_root"] == runtime_root.resolve()
    assert captured["postgres_database_url"] == "postgresql://example/postgres"
    assert captured["postgres_root"] == runtime_root.resolve().parent / f"{runtime_root.resolve().name}-postgres-smoke"
    assert captured["postgres_port"] == 8790


def test_cli_strict_release_check_requires_postgres_url(tmp_path):
    command = get_command(app)
    runner = CliRunner()

    result = runner.invoke(
        command,
        ["strict-release-check"],
        prog_name="memco",
    )

    assert result.exit_code != 0
    plain = _plain(result.output)
    assert "--postgres-database-url" in plain
    assert "required for strict-release-check" in plain


def test_cli_release_readiness_check_wraps_runner(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_release_readiness_check(
        *,
        project_root: Path,
        eval_root: Path | None,
        postgres_database_url: str,
        postgres_root: Path | None,
        postgres_port: int | None,
    ):
        captured["project_root"] = project_root
        captured["eval_root"] = eval_root
        captured["postgres_database_url"] = postgres_database_url
        captured["postgres_root"] = postgres_root
        captured["postgres_port"] = postgres_port
        return {
            "artifact_type": "release_readiness_check",
            "ok": False,
            "gate_type": "release-grade",
            "live_smoke_required": True,
            "steps": [{"name": "live_operator_smoke", "ok": False}],
        }

    monkeypatch.setattr("memco.cli.main.run_release_readiness_check", fake_run_release_readiness_check)
    runtime_root = tmp_path / "release-readiness-runtime"
    result = runner.invoke(
        command,
        [
            "release-readiness-check",
            "--root",
            str(runtime_root),
            "--postgres-database-url",
            "postgresql://example/postgres",
            "--postgres-port",
            "8791",
        ],
        prog_name="memco",
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "release_readiness_check"
    assert payload["gate_type"] == "release-grade"
    assert payload["live_smoke_required"] is True
    assert captured["project_root"] == Path.cwd().resolve()
    assert captured["eval_root"] == runtime_root.resolve()
    assert captured["postgres_database_url"] == "postgresql://example/postgres"
    assert captured["postgres_root"] == runtime_root.resolve().parent / f"{runtime_root.resolve().name}-postgres-smoke"
    assert captured["postgres_port"] == 8791


def test_cli_release_readiness_check_requires_postgres_url(tmp_path):
    command = get_command(app)
    runner = CliRunner()

    result = runner.invoke(
        command,
        ["release-readiness-check"],
        prog_name="memco",
    )

    assert result.exit_code != 0
    plain = _plain(result.output)
    assert "--postgres-database-url" in plain
    assert "release-readiness-check" in plain


def test_cli_operator_preflight_wraps_runner(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_operator_preflight(*, project_root: Path, postgres_database_url: str | None):
        captured["project_root"] = project_root
        captured["postgres_database_url"] = postgres_database_url
        return {
            "artifact_type": "operator_preflight",
            "ok": True,
            "steps": [{"name": "provider_reachability", "ok": True}],
        }

    monkeypatch.setattr("memco.cli.main.run_operator_preflight", fake_run_operator_preflight)
    repo_root = _seed_repo_root(tmp_path / "repo")
    output_path = tmp_path / "operator-preflight.json"
    result = runner.invoke(
        command,
        [
            "operator-preflight",
            "--project-root",
            str(repo_root),
            "--postgres-database-url",
            "postgresql://example/postgres",
            "--output",
            str(output_path),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "operator_preflight"
    assert payload["artifact_path"] == str(output_path.resolve())
    assert captured["project_root"] == repo_root.resolve()
    assert captured["postgres_database_url"] == "postgresql://example/postgres"

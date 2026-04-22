from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from typer.main import get_command

from memco.cli.main import app


def _seed_repo_root(path: Path) -> Path:
    (path / "src" / "memco").mkdir(parents=True, exist_ok=True)
    (path / "tests").mkdir(exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname='memco'\n", encoding="utf-8")
    (path / "README.md").write_text("# Memco\n", encoding="utf-8")
    return path


def test_cli_postgres_smoke_wraps_runner(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()

    def fake_run_postgres_smoke(*, database_url: str, root: Path, port: int | None, project_root: Path):
        return {
            "health": {"ok": True, "storage_engine": "postgres", "database_target": database_url},
            "schema_migrations": 1,
            "database_url": database_url,
            "root": str(root),
            "port": port or 8790,
        }

    monkeypatch.setattr("memco.cli.main.run_postgres_smoke", fake_run_postgres_smoke)
    result = runner.invoke(
        command,
        [
            "postgres-smoke",
            "--database-url",
            "postgresql://example/test",
            "--root",
            str(tmp_path / "runtime"),
            "--port",
            "8790",
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_migrations"] == 1
    assert payload["health"]["storage_engine"] == "postgres"
    assert payload["database_url"] == "postgresql://example/test"


def test_cli_postgres_smoke_supports_explicit_project_root(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()
    captured: dict[str, object] = {}
    repo_root = _seed_repo_root(tmp_path)

    def fake_run_postgres_smoke(*, database_url: str, root: Path, port: int | None, project_root: Path):
        captured["project_root"] = project_root
        return {
            "health": {"ok": True, "storage_engine": "postgres", "database_target": database_url},
            "schema_migrations": 1,
            "database_url": database_url,
            "root": str(root),
            "port": port or 8790,
        }

    monkeypatch.setattr("memco.cli.main.run_postgres_smoke", fake_run_postgres_smoke)
    result = runner.invoke(
        command,
        [
            "postgres-smoke",
            "--database-url",
            "postgresql://example/test",
            "--project-root",
            str(repo_root),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    assert captured["project_root"] == repo_root.resolve()


def test_cli_postgres_bootstrap_wraps_helper(monkeypatch, tmp_path):
    command = get_command(app)
    runner = CliRunner()

    monkeypatch.setattr(
        "memco.cli.main.ensure_postgres_database",
        lambda **kwargs: "postgresql://example/memco_db",
    )
    result = runner.invoke(
        command,
        [
            "postgres-bootstrap",
            "memco_db",
            "--database-url",
            "postgresql://example/postgres",
            "--root",
            str(tmp_path / "runtime"),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["db_name"] == "memco_db"
    assert payload["database_url"] == "postgresql://example/memco_db"
    assert "MEMCO_STORAGE_ENGINE=postgres" in payload["next"][0]

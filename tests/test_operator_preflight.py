from __future__ import annotations

import json
from pathlib import Path

from memco.artifact_semantics import evaluate_artifact_freshness
from memco.config import Settings, load_settings, write_settings
from memco.operator_preflight import run_operator_preflight


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, query: str):
        assert query == "SELECT 1"

    def fetchone(self):
        return (1,)


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def cursor(self):
        return _FakeCursor()


class _FakeProvider:
    name = "openai-compatible"
    model = "gpt-test"

    def complete_text(self, *, system_prompt: str, prompt: str, metadata=None):
        assert "preflight" in system_prompt.lower()
        assert "Reply" in prompt
        return type("Response", (), {"text": "ok"})()


def _write_preflight_settings(project_root: Path) -> None:
    settings = Settings(root=project_root)
    settings.storage.engine = "postgres"
    settings.storage.database_url = "postgresql://memco:memco@127.0.0.1:5432/memco_local"
    settings.storage.backup_path = "var/backups/memco-postgres.dump"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = ""
    settings.api.auth_token = "memco-token"
    settings.backup_path.parent.mkdir(parents=True, exist_ok=True)
    settings.backup_path.write_text("backup", encoding="utf-8")
    write_settings(settings)


def test_operator_preflight_reports_missing_live_credentials(tmp_path):
    project_root = tmp_path / "repo"
    _write_preflight_settings(project_root)

    result = run_operator_preflight(project_root=project_root)

    assert result["artifact_type"] == "operator_preflight"
    assert result["ok"] is False
    assert result["steps"][0]["name"] == "config_load"
    runtime_step = next(step for step in result["steps"] if step["name"] == "runtime_policy")
    assert runtime_step["ok"] is False
    assert runtime_step["operator_runtime_status"]["release_eligible"] is False
    assert "api_key" in runtime_step["reason"]
    provider_step = next(step for step in result["steps"] if step["name"] == "provider_reachability")
    assert provider_step["ok"] is False
    assert provider_step["skipped"] is True
    assert provider_step["reason"] == "runtime_policy_failed"


def test_operator_preflight_checks_backup_db_and_provider(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    _write_preflight_settings(project_root)
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")
    monkeypatch.setattr("memco.operator_preflight.psycopg.connect", lambda *_args, **_kwargs: _FakeConnection())
    monkeypatch.setattr("memco.operator_preflight.build_llm_provider", lambda _settings: _FakeProvider())

    result = run_operator_preflight(project_root=project_root)

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == [
        "config_load",
        "runtime_policy",
        "operator_env",
        "actor_policies",
        "backup_path",
        "db_reachability",
        "provider_reachability",
    ]
    assert next(step for step in result["steps"] if step["name"] == "operator_env")["ok"] is True
    assert next(step for step in result["steps"] if step["name"] == "actor_policies")["ok"] is True
    assert next(step for step in result["steps"] if step["name"] == "backup_path")["ok"] is True
    assert next(step for step in result["steps"] if step["name"] == "db_reachability")["ok"] is True
    assert next(step for step in result["steps"] if step["name"] == "provider_reachability")["ok"] is True


def test_operator_preflight_artifact_has_freshness_context(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    _write_preflight_settings(project_root)
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")
    monkeypatch.setattr("memco.operator_preflight.psycopg.connect", lambda *_args, **_kwargs: _FakeConnection())
    monkeypatch.setattr("memco.operator_preflight.build_llm_provider", lambda _settings: _FakeProvider())

    result = run_operator_preflight(project_root=project_root)

    assert result["artifact_context"]["runtime_mode"] == "repo-local"
    assert result["artifact_context"]["live_smoke"]["requested"] is False
    assert result["artifact_context"]["freshness"]["status"] == "current_at_generation"
    freshness = evaluate_artifact_freshness(result, project_root=project_root)
    assert freshness["current_for_checkout_config"] is True


def test_operator_preflight_reports_actor_policy_ids_without_tokens(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    _write_preflight_settings(project_root)
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")
    monkeypatch.setattr("memco.operator_preflight.psycopg.connect", lambda *_args, **_kwargs: _FakeConnection())
    monkeypatch.setattr("memco.operator_preflight.build_llm_provider", lambda _settings: _FakeProvider())

    result = run_operator_preflight(project_root=project_root)

    actor_step = next(step for step in result["steps"] if step["name"] == "actor_policies")
    assert actor_step["ok"] is True
    assert actor_step["actor_ids"] == ["dev-owner", "eval-runner", "maintenance-admin", "system"]
    assert actor_step["checks"] == {
        "actor_policies_configured": True,
        "dev_owner_actor": True,
        "maintenance_admin_actor": True,
        "system_actor": True,
    }
    actor_payload = json.dumps(actor_step)
    assert "auth_token" not in actor_payload
    for policy in load_settings(project_root).api.actor_policies.values():
        assert policy.auth_token not in actor_payload


def test_operator_preflight_reports_missing_backup_path(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    _write_preflight_settings(project_root)
    (project_root / "var/backups/memco-postgres.dump").unlink()
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")
    monkeypatch.setattr("memco.operator_preflight.psycopg.connect", lambda *_args, **_kwargs: _FakeConnection())
    monkeypatch.setattr("memco.operator_preflight.build_llm_provider", lambda _settings: _FakeProvider())

    result = run_operator_preflight(project_root=project_root)

    backup_step = next(step for step in result["steps"] if step["name"] == "backup_path")
    assert result["ok"] is False
    assert backup_step["ok"] is False
    assert backup_step["reason"] == "backup path does not exist"


def test_operator_preflight_reports_database_reachability_failure(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    _write_preflight_settings(project_root)
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")
    monkeypatch.setattr(
        "memco.operator_preflight.psycopg.connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    monkeypatch.setattr("memco.operator_preflight.build_llm_provider", lambda _settings: _FakeProvider())

    result = run_operator_preflight(project_root=project_root)

    db_step = next(step for step in result["steps"] if step["name"] == "db_reachability")
    assert result["ok"] is False
    assert db_step["ok"] is False
    assert db_step["reason"] == "RuntimeError: db down"

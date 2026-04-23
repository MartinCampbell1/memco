from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.config import Settings, write_settings


def test_health_returns_runtime_snapshot(monkeypatch, settings):
    monkeypatch.setenv("MEMCO_ROOT", str(settings.root))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert Path(payload["root"]) == settings.root
    assert Path(payload["db"]) == settings.db_path
    assert payload["storage_engine"] == "sqlite"
    assert payload["storage_contract_engine"] == "postgres"
    assert payload["storage_contract"] == "postgres-primary"
    assert payload["storage_role"] == "fallback"
    assert Path(payload["database_target"]) == settings.db_path
    assert payload["api_token_configured"] is False
    assert payload["backup_path"].endswith("var/backups/memco-postgres.dump")
    assert payload["backup_path_exists"] is False
    assert payload["llm_runtime"]["provider"] == "mock"
    assert payload["llm_runtime"]["runtime_profile"] == "fixture"
    assert payload["llm_runtime"]["credentials_present"] is False
    assert payload["llm_runtime"]["base_url_present"] is False
    assert payload["llm_runtime"]["provider_configured"] is False
    assert payload["llm_runtime"]["fixture_only"] is True
    assert payload["llm_runtime"]["release_eligible"] is False


def test_health_separates_checkout_and_env_injected_operator_runtime(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    settings.storage.engine = "sqlite"
    settings.llm.provider = "openai-compatible"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = ""
    write_settings(settings)
    monkeypatch.setenv("MEMCO_ROOT", str(project_root))
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "env-secret")
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm_runtime"]["release_eligible"] is True
    assert payload["llm_runtime_status"]["checkout_status"]["release_eligible"] is False
    assert payload["llm_runtime_status"]["checkout_status"]["credentials_present"] is False
    assert payload["llm_runtime_status"]["operator_runtime_status"]["release_eligible"] is True
    assert payload["llm_runtime_status"]["operator_runtime_status"]["credentials_present"] is True
    assert payload["llm_runtime_status"]["env_overrides"]["used"] is True
    assert "MEMCO_LLM_API_KEY" in payload["llm_runtime_status"]["env_overrides"]["present_keys"]
    assert payload["llm_runtime_status"]["config_only_red_operator_green"] is True

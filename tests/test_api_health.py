from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from memco.api.app import app


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

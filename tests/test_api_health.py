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
    assert Path(payload["database_target"]) == settings.db_path

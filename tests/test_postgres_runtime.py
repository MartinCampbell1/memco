from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.config import Settings
from memco.db import POSTGRES_BASE_VERSION, initialize_db


class _FakeRow(dict):
    pass


class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakePostgresConn:
    def __init__(self):
        self.engine = "postgres"
        self.applied_versions: set[str] = set()
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        if "SELECT version FROM schema_migrations" in normalized:
            version = params[0]
            if version in self.applied_versions:
                return _FakeCursor([_FakeRow({"version": version})])
            return _FakeCursor([])
        if "INSERT INTO schema_migrations" in normalized:
            self.applied_versions.add(params[0])
            return _FakeCursor([])
        if "SELECT COUNT(*) AS count FROM workspaces" in normalized:
            return _FakeCursor([_FakeRow({"count": 0})])
        if "SELECT COUNT(*) AS count FROM sources" in normalized:
            return _FakeCursor([_FakeRow({"count": 0})])
        if "SELECT COUNT(*) AS count FROM persons" in normalized:
            return _FakeCursor([_FakeRow({"count": 0})])
        if "SELECT COUNT(*) AS count FROM memory_facts" in normalized:
            return _FakeCursor([_FakeRow({"count": 0})])
        return _FakeCursor([])

    def executescript(self, script):
        self.statements.append(script)


def test_initialize_db_uses_postgres_base_migration(monkeypatch, tmp_path):
    fake_conn = _FakePostgresConn()
    monkeypatch.setenv("MEMCO_STORAGE_ENGINE", "postgres")
    monkeypatch.setenv("MEMCO_DATABASE_URL", "postgresql://memco:memco@db:5432/memco")
    monkeypatch.setattr("memco.db._postgres_connection", lambda database_url: fake_conn)

    db_path = tmp_path / "project" / "var" / "db" / "memco.db"
    initialize_db(db_path)

    assert POSTGRES_BASE_VERSION in fake_conn.applied_versions
    assert any("CREATE TABLE IF NOT EXISTS workspaces" in statement for statement in fake_conn.statements)
    assert any("CREATE OR REPLACE VIEW source_documents AS" in statement for statement in fake_conn.statements)


def test_health_reports_postgres_target(monkeypatch, tmp_path):
    settings = Settings(root=Path(tmp_path / "project"))
    settings.storage.engine = "postgres"
    settings.storage.database_url = "postgresql://memco:memco@db:5432/memco"
    fake_conn = _FakePostgresConn()

    monkeypatch.setattr("memco.api.routes.health.get_settings", lambda: settings)
    monkeypatch.setattr("memco.api.routes.health.get_connection", lambda _db_path: fake_conn)

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage_engine"] == "postgres"
    assert payload["db"] == "postgresql://memco:memco@db:5432/memco"
    assert payload["database_target"] == "postgresql://memco:memco@db:5432/memco"

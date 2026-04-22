from __future__ import annotations

from memco.config import Settings, load_settings, write_settings


def test_load_settings_accepts_env_overrides(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir(parents=True)
    monkeypatch.setenv("MEMCO_ROOT", str(root))
    monkeypatch.setenv("MEMCO_LLM_PROVIDER", "mock")
    monkeypatch.setenv("MEMCO_LLM_MODEL", "fixture-x")
    monkeypatch.setenv("MEMCO_LLM_BASE_URL", "https://router.example/v1")
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "test-key")
    monkeypatch.setenv("MEMCO_STORAGE_ENGINE", "postgres")
    monkeypatch.setenv("MEMCO_DATABASE_URL", "postgresql://memco:memco@db:5432/memco")

    settings = load_settings()

    assert settings.root == root.resolve()
    assert settings.llm.provider == "mock"
    assert settings.llm.model == "fixture-x"
    assert settings.llm.base_url == "https://router.example/v1"
    assert settings.llm.api_key == "test-key"
    assert settings.storage.engine == "postgres"
    assert settings.storage.database_url == "postgresql://memco:memco@db:5432/memco"


def test_write_settings_roundtrip(tmp_path):
    settings = Settings(root=tmp_path / "project")
    settings.api.port = 9898
    settings.llm.model = "fixture-y"

    write_settings(settings)
    loaded = load_settings(settings.root)

    assert loaded.api.port == 9898
    assert loaded.llm.model == "fixture-y"
    assert loaded.logging.query_hash_salt


def test_database_target_reflects_storage_engine(tmp_path):
    sqlite_settings = Settings(root=tmp_path / "sqlite-project")
    postgres_settings = Settings(root=tmp_path / "postgres-project")
    postgres_settings.storage.engine = "postgres"
    postgres_settings.storage.database_url = "postgresql://memco:memco@db:5432/memco"

    assert sqlite_settings.database_target == str(sqlite_settings.db_path)
    assert postgres_settings.database_target == "postgresql://memco:memco@db:5432/memco"

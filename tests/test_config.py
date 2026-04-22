from __future__ import annotations

from memco.config import PRIMARY_STORAGE_ENGINE, Settings, SQLITE_FALLBACK_ENGINE, load_settings, write_settings


def test_load_settings_accepts_env_overrides(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir(parents=True)
    monkeypatch.setenv("MEMCO_ROOT", str(root))
    monkeypatch.setenv("MEMCO_LLM_PROVIDER", "mock")
    monkeypatch.setenv("MEMCO_LLM_MODEL", "fixture-x")
    monkeypatch.setenv("MEMCO_LLM_BASE_URL", "https://router.example/v1")
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "test-key")
    monkeypatch.setenv("MEMCO_LLM_ALLOW_MOCK_PROVIDER", "true")
    monkeypatch.setenv("MEMCO_STORAGE_ENGINE", "postgres")
    monkeypatch.setenv("MEMCO_DATABASE_URL", "postgresql://memco:memco@db:5432/memco")
    monkeypatch.setenv("MEMCO_RUNTIME_PROFILE", "fixture")

    settings = load_settings()

    assert settings.root == root.resolve()
    assert settings.llm.provider == "mock"
    assert settings.llm.model == "fixture-x"
    assert settings.llm.base_url == "https://router.example/v1"
    assert settings.llm.api_key == "test-key"
    assert settings.llm.allow_mock_provider is True
    assert settings.storage.engine == "postgres"
    assert settings.storage.database_url == "postgresql://memco:memco@db:5432/memco"
    assert settings.runtime.profile == "fixture"


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
    sqlite_settings.storage.engine = "sqlite"
    postgres_settings = Settings(root=tmp_path / "postgres-project")
    postgres_settings.storage.engine = "postgres"
    postgres_settings.storage.database_url = "postgresql://memco:memco@db:5432/memco"

    assert sqlite_settings.database_target == str(sqlite_settings.db_path)
    assert postgres_settings.database_target == "postgresql://memco:memco@db:5432/memco"


def test_storage_contract_defaults_to_postgres_primary(tmp_path):
    settings = Settings(root=tmp_path / "project")

    assert settings.storage.contract_engine == PRIMARY_STORAGE_ENGINE
    assert settings.storage.engine == PRIMARY_STORAGE_ENGINE
    assert settings.storage_contract == "postgres-primary"
    assert settings.storage_role == "primary"


def test_storage_role_is_fallback_when_runtime_uses_sqlite(tmp_path):
    settings = Settings(root=tmp_path / "project")
    settings.storage.engine = SQLITE_FALLBACK_ENGINE

    assert settings.storage_role == "fallback"


def test_llm_runtime_defaults_to_openai_compatible_provider(tmp_path):
    settings = Settings(root=tmp_path / "project")

    assert settings.llm.provider == "openai-compatible"
    assert settings.llm.allow_mock_provider is False
    assert settings.runtime.profile == "repo-local"


def test_load_settings_does_not_treat_mock_provider_in_config_as_implicit_opt_in(tmp_path):
    root = tmp_path / "project"
    (root / "var" / "config").mkdir(parents=True, exist_ok=True)
    (root / "var" / "config" / "settings.yaml").write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "  model: fixture-x",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = load_settings(root)

    assert loaded.llm.provider == "mock"
    assert loaded.llm.allow_mock_provider is False


def test_load_settings_preserves_explicit_mock_opt_in_from_config(tmp_path):
    root = tmp_path / "project"
    (root / "var" / "config").mkdir(parents=True, exist_ok=True)
    (root / "var" / "config" / "settings.yaml").write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "  model: fixture-x",
                "  allow_mock_provider: true",
                "runtime:",
                "  profile: fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = load_settings(root)

    assert loaded.llm.provider == "mock"
    assert loaded.llm.allow_mock_provider is True
    assert loaded.runtime.profile == "fixture"


def test_ingest_source_types_match_current_repo_local_contract(tmp_path):
    settings = Settings(root=tmp_path / "project")

    assert {"text", "markdown", "chat", "json", "csv", "email", "pdf"} <= set(settings.ingest.source_types)
    assert "whatsapp" not in settings.ingest.source_types
    assert "telegram" not in settings.ingest.source_types

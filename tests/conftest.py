from __future__ import annotations

from pathlib import Path

import pytest

from memco.config import Settings
from memco.runtime import ensure_runtime


@pytest.fixture(autouse=True)
def isolate_memco_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MEMCO_ROOT",
        "MEMCO_API_HOST",
        "MEMCO_API_PORT",
        "MEMCO_API_TOKEN",
        "MEMCO_REQUIRE_ACTOR_SCOPE",
        "MEMCO_LLM_PROVIDER",
        "MEMCO_LLM_MODEL",
        "MEMCO_LLM_BASE_URL",
        "MEMCO_LLM_API_KEY",
        "MEMCO_LLM_ALLOW_MOCK_PROVIDER",
        "MEMCO_STORAGE_ENGINE",
        "MEMCO_DATABASE_URL",
        "MEMCO_BACKUP_PATH",
        "MEMCO_ENABLE_RETRIEVAL_LOGS",
        "MEMCO_QUERY_HASH_SALT",
        "MEMCO_RUNTIME_PROFILE",
        "MEMCO_RUN_LIVE_SMOKE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    return tmp_path / "memco-project"


@pytest.fixture()
def settings(project_root: Path) -> Settings:
    config = Settings(root=project_root)
    config.runtime.profile = "fixture"
    config.storage.engine = "sqlite"
    config.llm.provider = "mock"
    config.llm.model = "fixture"
    config.llm.allow_mock_provider = True
    return ensure_runtime(config)

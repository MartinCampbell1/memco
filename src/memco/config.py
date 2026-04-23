from __future__ import annotations

from copy import deepcopy
import os
import secrets
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


PRIMARY_STORAGE_ENGINE = "postgres"
SQLITE_FALLBACK_ENGINE = "sqlite"
SUPPORTED_STORAGE_ENGINES = {PRIMARY_STORAGE_ENGINE, SQLITE_FALLBACK_ENGINE}


class ApiActorPolicy(BaseModel):
    actor_type: Literal["system", "owner", "admin", "eval"]
    auth_token: str
    can_view_sensitive: bool = False
    allowed_person_ids: list[int] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)


def _default_actor_policies() -> dict[str, ApiActorPolicy]:
    return {
        "system": ApiActorPolicy(actor_type="system", auth_token=secrets.token_hex(16), can_view_sensitive=True),
        "dev-owner": ApiActorPolicy(actor_type="owner", auth_token=secrets.token_hex(16), can_view_sensitive=True),
        "maintenance-admin": ApiActorPolicy(actor_type="admin", auth_token=secrets.token_hex(16), can_view_sensitive=False),
        "eval-runner": ApiActorPolicy(actor_type="eval", auth_token=secrets.token_hex(16), can_view_sensitive=False),
    }


class ApiSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8788
    auth_token: str = ""
    require_actor_scope: bool = False
    actor_policies: dict[str, ApiActorPolicy] = Field(default_factory=_default_actor_policies)


class LLMSettings(BaseModel):
    provider: str = "openai-compatible"
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    allow_mock_provider: bool = False


class StorageSettings(BaseModel):
    engine: str = PRIMARY_STORAGE_ENGINE
    contract_engine: str = PRIMARY_STORAGE_ENGINE
    db_path: str = "var/db/memco.db"
    database_url: str = "postgresql://martin@127.0.0.1:5432/memco_local"
    backup_path: str = "var/backups/memco-postgres.dump"

    @field_validator("engine", "contract_engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_STORAGE_ENGINES:
            supported = ", ".join(sorted(SUPPORTED_STORAGE_ENGINES))
            raise ValueError(f"storage engine must be one of: {supported}")
        return normalized


class IngestSettings(BaseModel):
    max_chunk_chars: int = 2200
    max_tokens_per_chunk: int = 400
    overlap_tokens: int = 40
    session_gap_minutes: int = 240
    source_types: list[str] = Field(
        default_factory=lambda: ["note", "chat", "json", "csv", "markdown", "text", "email", "pdf"]
    )


class LoggingSettings(BaseModel):
    enable_retrieval_logs: bool = True
    query_hash_salt: str = ""


class RuntimeSettings(BaseModel):
    profile: Literal["repo-local", "fixture"] = "repo-local"


class Settings(BaseModel):
    root: Path
    default_workspace: str = "default"
    timezone: str = "UTC"
    api: ApiSettings = Field(default_factory=ApiSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)

    @property
    def db_path(self) -> Path:
        return self.root / self.storage.db_path

    @property
    def database_target(self) -> str:
        if self.storage.engine == PRIMARY_STORAGE_ENGINE:
            return self.storage.database_url
        return str(self.db_path)

    @property
    def storage_contract(self) -> str:
        return f"{self.storage.contract_engine}-primary"

    @property
    def storage_role(self) -> str:
        return "primary" if self.storage.engine == self.storage.contract_engine else "fallback"

    @property
    def backup_path(self) -> Path:
        return self.root / self.storage.backup_path

    @property
    def config_path(self) -> Path:
        return self.root / "var" / "config" / "settings.yaml"

    @property
    def runtime_profile(self) -> str:
        return self.runtime.profile

    @property
    def is_fixture_runtime(self) -> bool:
        return self.runtime.profile == "fixture"


def discover_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser().resolve()
    env_value = os.environ.get("MEMCO_ROOT")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return Path.cwd().resolve()


def _settings_payload(settings: Settings) -> dict:
    return {
        "default_workspace": settings.default_workspace,
        "timezone": settings.timezone,
        "api": settings.api.model_dump(),
        "llm": settings.llm.model_dump(),
        "storage": settings.storage.model_dump(),
        "ingest": settings.ingest.model_dump(),
        "logging": settings.logging.model_dump(),
        "runtime": settings.runtime.model_dump(),
    }


def _has_actor_policies(raw_data: dict) -> bool:
    api = raw_data.get("api")
    if not isinstance(api, dict):
        return False
    actor_policies = api.get("actor_policies")
    return isinstance(actor_policies, dict) and bool(actor_policies)


def _actor_policies_payload(settings: Settings) -> dict:
    return {actor_id: policy.model_dump() for actor_id, policy in settings.api.actor_policies.items()}


def _secure_config_path(config_path: Path) -> None:
    if os.name != "posix":
        return
    try:
        if config_path.parent.exists():
            config_path.parent.chmod(0o700)
        if config_path.exists():
            config_path.chmod(0o600)
    except OSError:
        return


def _ensure_config_parent(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _secure_config_path(config_path)


def _write_config_payload(config_path: Path, payload: dict) -> None:
    _ensure_config_parent(config_path)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
    _secure_config_path(config_path)


def _backfill_actor_policies(config_path: Path, raw_file_data: dict, settings: Settings) -> None:
    if _has_actor_policies(raw_file_data):
        return
    updated = deepcopy(raw_file_data)
    api = updated.get("api")
    if not isinstance(api, dict):
        api = {}
        updated["api"] = api
    api["actor_policies"] = _actor_policies_payload(settings)
    _write_config_payload(config_path, updated)


def load_settings(root: str | Path | None = None, *, apply_env: bool = True) -> Settings:
    resolved_root = discover_root(root)
    config_path = resolved_root / "var" / "config" / "settings.yaml"
    raw_file_data: dict = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            raw_file_data = yaml.safe_load(handle) or {}
    raw_data: dict = deepcopy(raw_file_data)

    env_timezone = os.environ.get("MEMCO_TIMEZONE") if apply_env else None
    env_api_host = os.environ.get("MEMCO_API_HOST") if apply_env else None
    env_api_port = os.environ.get("MEMCO_API_PORT") if apply_env else None
    env_api_token = os.environ.get("MEMCO_API_TOKEN") if apply_env else None
    env_require_actor_scope = os.environ.get("MEMCO_REQUIRE_ACTOR_SCOPE") if apply_env else None
    env_llm_provider = os.environ.get("MEMCO_LLM_PROVIDER") if apply_env else None
    env_llm_model = os.environ.get("MEMCO_LLM_MODEL") if apply_env else None
    env_llm_base_url = os.environ.get("MEMCO_LLM_BASE_URL") if apply_env else None
    env_llm_api_key = os.environ.get("MEMCO_LLM_API_KEY") if apply_env else None
    env_llm_allow_mock_provider = os.environ.get("MEMCO_LLM_ALLOW_MOCK_PROVIDER") if apply_env else None
    env_storage_engine = os.environ.get("MEMCO_STORAGE_ENGINE") if apply_env else None
    env_database_url = os.environ.get("MEMCO_DATABASE_URL") if apply_env else None
    env_backup_path = os.environ.get("MEMCO_BACKUP_PATH") if apply_env else None
    env_enable_retrieval_logs = os.environ.get("MEMCO_ENABLE_RETRIEVAL_LOGS") if apply_env else None
    env_query_hash_salt = os.environ.get("MEMCO_QUERY_HASH_SALT") if apply_env else None
    env_runtime_profile = os.environ.get("MEMCO_RUNTIME_PROFILE") if apply_env else None

    if env_timezone:
        raw_data["timezone"] = env_timezone
    if env_api_host:
        api = raw_data.setdefault("api", {})
        api["host"] = env_api_host
    if env_api_port:
        api = raw_data.setdefault("api", {})
        api["port"] = int(env_api_port)
    if env_api_token is not None:
        api = raw_data.setdefault("api", {})
        api["auth_token"] = env_api_token
    if env_require_actor_scope is not None:
        api = raw_data.setdefault("api", {})
        api["require_actor_scope"] = env_require_actor_scope.strip().lower() in {"1", "true", "yes", "on"}
    if env_llm_provider:
        llm = raw_data.setdefault("llm", {})
        llm["provider"] = env_llm_provider
    if env_llm_model:
        llm = raw_data.setdefault("llm", {})
        llm["model"] = env_llm_model
    if env_llm_base_url:
        llm = raw_data.setdefault("llm", {})
        llm["base_url"] = env_llm_base_url
    if env_llm_api_key is not None:
        llm = raw_data.setdefault("llm", {})
        llm["api_key"] = env_llm_api_key
    if env_llm_allow_mock_provider is not None:
        llm = raw_data.setdefault("llm", {})
        llm["allow_mock_provider"] = env_llm_allow_mock_provider.strip().lower() in {"1", "true", "yes", "on"}
    if env_storage_engine:
        storage = raw_data.setdefault("storage", {})
        storage["engine"] = env_storage_engine
    if env_database_url is not None:
        storage = raw_data.setdefault("storage", {})
        storage["database_url"] = env_database_url
    if env_backup_path is not None:
        storage = raw_data.setdefault("storage", {})
        storage["backup_path"] = env_backup_path
    if env_enable_retrieval_logs is not None:
        logging = raw_data.setdefault("logging", {})
        logging["enable_retrieval_logs"] = env_enable_retrieval_logs.strip().lower() in {"1", "true", "yes", "on"}
    if env_query_hash_salt is not None:
        logging = raw_data.setdefault("logging", {})
        logging["query_hash_salt"] = env_query_hash_salt
    if env_runtime_profile:
        runtime = raw_data.setdefault("runtime", {})
        runtime["profile"] = env_runtime_profile

    raw_data["root"] = resolved_root
    settings = Settings.model_validate(raw_data)
    if not settings.logging.query_hash_salt:
        settings.logging.query_hash_salt = secrets.token_hex(16)
    if config_path.exists():
        _backfill_actor_policies(config_path, raw_file_data, settings)
        _secure_config_path(config_path)
    return settings


def write_default_config(settings: Settings) -> None:
    _ensure_config_parent(settings.config_path)
    if settings.config_path.exists():
        _secure_config_path(settings.config_path)
        return
    _write_config_payload(settings.config_path, _settings_payload(settings))


def write_settings(settings: Settings) -> None:
    _write_config_payload(settings.config_path, _settings_payload(settings))

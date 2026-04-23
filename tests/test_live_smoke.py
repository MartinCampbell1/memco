from __future__ import annotations

import json
from pathlib import Path

from memco.config import Settings, write_settings
from memco.live_smoke import run_live_operator_smoke


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int | None = None) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - defensive
        self.killed = True


def test_run_live_operator_smoke_emits_compact_artifact(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    project_root = tmp_path / "repo"
    output_path = tmp_path / "artifacts" / "live-operator-smoke.json"
    project_root.mkdir()
    monkeypatch.setenv("MEMCO_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("MEMCO_LLM_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("MEMCO_LLM_BASE_URL", "http://127.0.0.1:2455/v1")
    monkeypatch.setenv("MEMCO_LLM_API_KEY", "secret")
    monkeypatch.setenv("MEMCO_API_TOKEN", "smoke-token")
    monkeypatch.setattr(
        "memco.live_smoke.ensure_postgres_database",
        lambda **kwargs: "postgresql://martin@127.0.0.1:5432/memco_live_smoke_12345",
    )
    monkeypatch.setattr("memco.live_smoke.drop_postgres_database", lambda **kwargs: None)
    monkeypatch.setattr("memco.live_smoke.ensure_runtime", lambda settings: settings)
    monkeypatch.setattr("memco.live_smoke.subprocess.Popen", lambda *args, **kwargs: _FakeProcess())

    def fake_wait_http(url: str, *, timeout_seconds: int = 30):
        assert url.endswith("/health")
        return {
            "storage_engine": "postgres",
            "storage_role": "primary",
            "llm_runtime": {"release_eligible": True},
        }

    def fake_request_json(*, url: str, method: str = "GET", payload=None, headers=None, timeout: int = 60, retries: int = 0):
        if url.endswith("/v1/ingest/pipeline") and payload["person_slug"] == "alice":
            return {
                "published": [
                    {"fact": {"domain": "biography", "category": "residence"}},
                    {"fact": {"domain": "preferences", "category": "preference"}},
                    {"fact": {"domain": "work", "category": "org"}},
                    {"fact": {"domain": "work", "category": "role"}},
                    {"fact": {"domain": "work", "category": "tool"}},
                    {"fact": {"domain": "experiences", "category": "event"}},
                ],
                "pending_review_items": [],
            }
        if url.endswith("/v1/ingest/pipeline") and payload["person_slug"] == "bob":
            return {
                "published": [
                    {"fact": {"domain": "biography", "category": "residence"}},
                    {"fact": {"domain": "preferences", "category": "preference"}},
                    {"fact": {"domain": "work", "category": "org"}},
                    {"fact": {"domain": "work", "category": "role"}},
                ],
                "pending_review_items": [],
            }
        if url.endswith("/v1/retrieve") and payload["person_slug"] == "alice":
            return {
                "hits": [
                    {
                        "fact_id": 1,
                        "domain": "biography",
                        "category": "residence",
                        "summary": "Alice lives in Lisbon.",
                        "evidence": [{"evidence_id": 10}],
                    }
                ]
            }
        if url.endswith("/v1/retrieve") and payload["person_slug"] == "bob":
            return {
                "hits": [
                    {
                        "fact_id": 2,
                        "domain": "biography",
                        "category": "residence",
                        "summary": "Bob lives in Porto.",
                        "evidence": [{"evidence_id": 20}],
                    }
                ]
            }
        if url.endswith("/v1/chat") and payload["query"] == "Where does Alice live?":
            return {
                "refused": False,
                "answer": "Alice lives in Lisbon.",
                "fact_ids": [1],
                "evidence_ids": [10],
            }
        if url.endswith("/v1/chat") and payload["query"] in {
            "Is Bob Alice's brother?",
            "Does Alice live in Berlin?",
            "Where does Bob live?",
        }:
            return {
                "refused": True,
                "answer": "I don't have confirmed memory evidence for that.",
                "fact_ids": [],
                "evidence_ids": [],
            }
        raise AssertionError(f"Unexpected request: {method} {url} {payload}")

    monkeypatch.setattr("memco.live_smoke._wait_http", fake_wait_http)
    monkeypatch.setattr("memco.live_smoke._request_json", fake_request_json)

    result = run_live_operator_smoke(
        maintenance_database_url="postgresql://martin@127.0.0.1:5432/postgres",
        root=root,
        project_root=project_root,
        output_path=output_path,
    )

    assert result["artifact_type"] == "live_operator_smoke"
    assert result["ok"] is True
    assert result["provider"] == "openai-compatible"
    assert result["storage_engine"] == "postgres"
    assert result["storage_role"] == "primary"
    assert result["failures"] == []
    assert output_path.exists()
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert any(step["name"] == "ingest_pipeline" for step in written["steps"])
    assert any(step["name"] == "api_queries" for step in written["steps"])


def test_run_live_operator_smoke_uses_project_config_when_env_is_absent(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    project_root = tmp_path / "repo"
    output_path = tmp_path / "artifacts" / "live-operator-smoke.json"
    project_settings = Settings(root=project_root)
    project_settings.llm.provider = "openai-compatible"
    project_settings.llm.model = "gpt-5.4-mini"
    project_settings.llm.base_url = "http://127.0.0.1:2455/v1"
    project_settings.llm.api_key = "config-secret"
    project_settings.api.auth_token = "config-token"
    write_settings(project_settings)

    monkeypatch.setattr(
        "memco.live_smoke.ensure_postgres_database",
        lambda **kwargs: "postgresql://martin@127.0.0.1:5432/memco_live_smoke_12345",
    )
    monkeypatch.setattr("memco.live_smoke.drop_postgres_database", lambda **kwargs: None)
    monkeypatch.setattr("memco.live_smoke.ensure_runtime", lambda settings: settings)
    monkeypatch.setattr("memco.live_smoke.subprocess.Popen", lambda *args, **kwargs: _FakeProcess())

    def fake_wait_http(url: str, *, timeout_seconds: int = 30):
        assert url.endswith("/health")
        return {
            "storage_engine": "postgres",
            "storage_role": "primary",
            "llm_runtime": {"release_eligible": True},
        }

    def fake_request_json(*, url: str, method: str = "GET", payload=None, headers=None, timeout: int = 60, retries: int = 0):
        assert headers["X-Memco-Token"] == "config-token"
        if url.endswith("/v1/ingest/pipeline") and payload["person_slug"] == "alice":
            return {
                "published": [
                    {"fact": {"domain": "biography", "category": "residence"}},
                    {"fact": {"domain": "preferences", "category": "preference"}},
                    {"fact": {"domain": "work", "category": "org"}},
                    {"fact": {"domain": "work", "category": "role"}},
                    {"fact": {"domain": "work", "category": "tool"}},
                    {"fact": {"domain": "experiences", "category": "event"}},
                ],
                "pending_review_items": [],
            }
        if url.endswith("/v1/ingest/pipeline") and payload["person_slug"] == "bob":
            return {
                "published": [
                    {"fact": {"domain": "biography", "category": "residence"}},
                    {"fact": {"domain": "preferences", "category": "preference"}},
                    {"fact": {"domain": "work", "category": "org"}},
                    {"fact": {"domain": "work", "category": "role"}},
                ],
                "pending_review_items": [],
            }
        if url.endswith("/v1/retrieve"):
            return {"hits": [{"fact_id": 1, "evidence": [{"evidence_id": 10}]}]}
        if url.endswith("/v1/chat") and payload["query"] == "Where does Alice live?":
            return {"refused": False, "answer": "Alice lives in Lisbon.", "fact_ids": [1], "evidence_ids": [10]}
        if url.endswith("/v1/chat"):
            return {"refused": True, "answer": "I don't have confirmed memory evidence for that.", "fact_ids": [], "evidence_ids": []}
        raise AssertionError(f"Unexpected request: {method} {url} {payload}")

    monkeypatch.setattr("memco.live_smoke._wait_http", fake_wait_http)
    monkeypatch.setattr("memco.live_smoke._request_json", fake_request_json)

    result = run_live_operator_smoke(
        maintenance_database_url="postgresql://martin@127.0.0.1:5432/postgres",
        root=root,
        project_root=project_root,
        output_path=output_path,
    )

    assert result["ok"] is True
    assert result["provider"] == "openai-compatible"
    assert result["model"] == "gpt-5.4-mini"
    assert result["base_url"] == "http://127.0.0.1:2455/v1"
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["ok"] is True

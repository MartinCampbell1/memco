from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from memco.api.deps import build_internal_actor
from memco.config import Settings, load_settings, write_settings
from memco.postgres_admin import drop_postgres_database, ensure_postgres_database
from memco.runtime import ensure_runtime


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _headers(*, api_token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_token.strip():
        headers["X-Memco-Token"] = api_token.strip()
    return headers


def _request_json(
    *,
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    retries: int = 0,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            request = urllib.request.Request(
                url=url,
                data=data,
                headers=headers or {},
                method=method,
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500 or attempt >= retries:
                raise
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _wait_http(url: str, *, timeout_seconds: int = 30) -> dict[str, Any]:
    started = time.time()
    last_error: Exception | None = None
    while time.time() - started < timeout_seconds:
        try:
            return _request_json(url=url, timeout=5)
        except Exception as exc:  # pragma: no cover - exercised in live runs
            last_error = exc
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _runtime_settings(
    *,
    root: Path,
    database_url: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    api_token: str,
) -> Settings:
    settings = Settings(root=root)
    settings.runtime.profile = "repo-local"
    settings.storage.engine = "postgres"
    settings.storage.database_url = database_url
    settings.llm.provider = provider
    settings.llm.model = model
    settings.llm.base_url = base_url
    settings.llm.api_key = api_key
    settings.api.auth_token = api_token
    write_settings(settings)
    return ensure_runtime(settings)


def _source_file(root: Path, *, filename: str, messages: list[dict[str, str]]) -> Path:
    path = root / "var" / "smoke" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"messages": messages}, ensure_ascii=False), encoding="utf-8")
    return path


def _fact_categories(pipeline_payload: dict[str, Any]) -> set[tuple[str, str]]:
    categories: set[tuple[str, str]] = set()
    for item in pipeline_payload.get("published", []):
        fact = item.get("fact") or {}
        domain = str(fact.get("domain") or "")
        category = str(fact.get("category") or "")
        if domain and category:
            categories.add((domain, category))
    return categories


def _step(*, name: str, ok: bool, **payload: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, **payload}


def run_live_operator_smoke(
    *,
    maintenance_database_url: str,
    root: Path,
    project_root: Path,
    port: int | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    project_settings = load_settings(project_root)
    provider = os.environ.get("MEMCO_LLM_PROVIDER", "").strip() or project_settings.llm.provider or "openai-compatible"
    model = os.environ.get("MEMCO_LLM_MODEL", "").strip() or project_settings.llm.model or "gpt-4o-mini"
    base_url = os.environ.get("MEMCO_LLM_BASE_URL", "").strip() or project_settings.llm.base_url.strip()
    api_key = os.environ.get("MEMCO_LLM_API_KEY", "").strip() or project_settings.llm.api_key.strip()
    api_token = os.environ.get("MEMCO_API_TOKEN", "").strip() or project_settings.api.auth_token.strip() or "memco-live-smoke-token"
    if not base_url:
        raise ValueError("MEMCO_LLM_BASE_URL is required for live smoke")
    if not api_key:
        raise ValueError("MEMCO_LLM_API_KEY is required for live smoke")

    selected_port = int(port or _free_port())
    db_name = f"memco_live_smoke_{random.randint(10000, 99999)}"
    run_db_url = ensure_postgres_database(
        maintenance_database_url=maintenance_database_url,
        db_name=db_name,
    )
    settings = _runtime_settings(
        root=root,
        database_url=run_db_url,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        api_token=api_token,
    )
    admin_actor = build_internal_actor(settings, actor_id="maintenance-admin").model_dump(mode="json")
    owner_actor = build_internal_actor(settings, actor_id="dev-owner").model_dump(mode="json")

    alice_source = _source_file(
        root,
        filename="alice_live_smoke.json",
        messages=[
            {"speaker": "Alice", "timestamp": "2026-04-21T09:00:00Z", "text": "I live in Lisbon."},
            {"speaker": "Alice", "timestamp": "2026-04-21T09:01:00Z", "text": "I like tea."},
            {"speaker": "Alice", "timestamp": "2026-04-21T09:02:00Z", "text": "I work at Acme."},
            {"speaker": "Alice", "timestamp": "2026-04-21T09:03:00Z", "text": "I am a product designer."},
            {"speaker": "Alice", "timestamp": "2026-04-21T09:04:00Z", "text": "I use Figma."},
            {"speaker": "Alice", "timestamp": "2026-04-21T09:05:00Z", "text": "I attended PyCon in 2024 with Bob."},
        ],
    )
    bob_source = _source_file(
        root,
        filename="bob_live_smoke.json",
        messages=[
            {"speaker": "Bob", "timestamp": "2026-04-21T10:00:00Z", "text": "I live in Porto."},
            {"speaker": "Bob", "timestamp": "2026-04-21T10:01:00Z", "text": "I like coffee."},
            {"speaker": "Bob", "timestamp": "2026-04-21T10:02:00Z", "text": "I work at Contoso."},
            {"speaker": "Bob", "timestamp": "2026-04-21T10:03:00Z", "text": "I am an engineer."},
        ],
    )

    env = {
        **os.environ,
        "MEMCO_ROOT": str(root),
        "MEMCO_API_HOST": "127.0.0.1",
        "MEMCO_API_PORT": str(selected_port),
    }
    process = subprocess.Popen(
        ["uv", "run", "memco-api"],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    failures: list[str] = []
    steps: list[dict[str, Any]] = []
    artifact: dict[str, Any] = {}
    try:
        base = f"http://127.0.0.1:{selected_port}"
        health = _wait_http(f"{base}/health")
        steps.append(
            _step(
                name="health",
                ok=health.get("storage_engine") == "postgres" and bool(health.get("llm_runtime", {}).get("release_eligible")),
                storage_engine=health.get("storage_engine"),
                storage_role=health.get("storage_role"),
                release_eligible=health.get("llm_runtime", {}).get("release_eligible"),
            )
        )

        request_headers = _headers(api_token=api_token)
        alice_pipeline = _request_json(
            url=f"{base}/v1/ingest/pipeline",
            method="POST",
            headers=request_headers,
            retries=2,
            payload={
                "workspace": "default",
                "path": str(alice_source),
                "source_type": "json",
                "person_display_name": "Alice",
                "person_slug": "alice",
                "aliases": ["Alice"],
                "actor": admin_actor,
            },
        )
        bob_pipeline = _request_json(
            url=f"{base}/v1/ingest/pipeline",
            method="POST",
            headers=request_headers,
            retries=2,
            payload={
                "workspace": "default",
                "path": str(bob_source),
                "source_type": "json",
                "person_display_name": "Bob",
                "person_slug": "bob",
                "aliases": ["Bob"],
                "actor": admin_actor,
            },
        )
        published_total = len(alice_pipeline.get("published", [])) + len(bob_pipeline.get("published", []))
        published_categories = sorted(_fact_categories(alice_pipeline) | _fact_categories(bob_pipeline))
        steps.append(
            _step(
                name="ingest_pipeline",
                ok=published_total >= 8,
                published_total=published_total,
                published_categories=published_categories,
                pending_review_total=len(alice_pipeline.get("pending_review_items", []))
                + len(bob_pipeline.get("pending_review_items", [])),
            )
        )

        alice_retrieve = _request_json(
            url=f"{base}/v1/retrieve",
            method="POST",
            headers=request_headers,
            retries=1,
            payload={
                "workspace": "default",
                "person_slug": "alice",
                "query": "Where does Alice live?",
                "detail_policy": "core_only",
                "actor": owner_actor,
            },
        )
        bob_retrieve = _request_json(
            url=f"{base}/v1/retrieve",
            method="POST",
            headers=request_headers,
            retries=1,
            payload={
                "workspace": "default",
                "person_slug": "bob",
                "query": "Where does Bob live?",
                "detail_policy": "core_only",
                "actor": owner_actor,
            },
        )
        supported_chat = _request_json(
            url=f"{base}/v1/chat",
            method="POST",
            headers=request_headers,
            retries=1,
            payload={
                "workspace": "default",
                "person_slug": "alice",
                "query": "Where does Alice live?",
                "detail_policy": "core_only",
                "actor": owner_actor,
            },
        )
        unsupported_chat = _request_json(
            url=f"{base}/v1/chat",
            method="POST",
            headers=request_headers,
            retries=1,
            payload={
                "workspace": "default",
                "person_slug": "alice",
                "query": "Is Bob Alice's brother?",
                "actor": owner_actor,
            },
        )
        contradicted_chat = _request_json(
            url=f"{base}/v1/chat",
            method="POST",
            headers=request_headers,
            retries=1,
            payload={
                "workspace": "default",
                "person_slug": "alice",
                "query": "Does Alice live in Berlin?",
                "actor": owner_actor,
            },
        )
        isolation_chat = _request_json(
            url=f"{base}/v1/chat",
            method="POST",
            headers=request_headers,
            retries=1,
            payload={
                "workspace": "default",
                "person_slug": "alice",
                "query": "Where does Bob live?",
                "actor": owner_actor,
            },
        )
        alice_residence_hit_ids = {
            int(hit.get("fact_id"))
            for hit in alice_retrieve.get("hits", [])
            if hit.get("fact_id") is not None
            and hit.get("domain") == "biography"
            and hit.get("category") == "residence"
            and "lisbon" in json.dumps(hit, ensure_ascii=False).lower()
        }
        supported_chat_fact_ids = {
            int(fact_id)
            for fact_id in [*supported_chat.get("fact_ids", []), *supported_chat.get("used_fact_ids", [])]
            if fact_id is not None
        }
        alice_answer_text = str(supported_chat.get("answer") or "").lower()
        checks = {
            "alice_retrieve_supported": bool(alice_residence_hit_ids),
            "bob_retrieve_supported": bool(bob_retrieve.get("hits")),
            "supported_chat_has_fact_ids": not supported_chat.get("refused", True)
            and bool(supported_chat.get("fact_ids"))
            and bool(supported_chat.get("evidence_ids")),
            "supported_chat_used_llm_planner": supported_chat.get("retrieval", {}).get("planner", {}).get("plan_version") == "v2_llm",
            "supported_chat_used_llm_answer_ids": not supported_chat.get("refused", True)
            and bool(supported_chat.get("used_fact_ids"))
            and bool(supported_chat.get("used_evidence_ids")),
            "supported_chat_mentions_expected_residence": "lisbon" in alice_answer_text,
            "supported_chat_excludes_preference_value": "tea" not in alice_answer_text,
            "supported_chat_uses_residence_fact": bool(alice_residence_hit_ids & supported_chat_fact_ids),
            "unsupported_premise_refused": bool(unsupported_chat.get("refused")),
            "contradicted_premise_refused": bool(contradicted_chat.get("refused")),
            "subject_isolation_refused": bool(isolation_chat.get("refused")),
        }
        steps.append(
            _step(
                name="api_queries",
                ok=all(checks.values()),
                checks=checks,
                alice_answer=supported_chat.get("answer"),
                alice_fact_ids=supported_chat.get("fact_ids", []),
                alice_evidence_ids=supported_chat.get("evidence_ids", []),
                alice_used_fact_ids=supported_chat.get("used_fact_ids", []),
                alice_used_evidence_ids=supported_chat.get("used_evidence_ids", []),
                alice_expected_residence_fact_ids=sorted(alice_residence_hit_ids),
                alice_planner_version=supported_chat.get("retrieval", {}).get("planner", {}).get("plan_version", ""),
            )
        )

        for step in steps:
            if not step["ok"]:
                failures.append(step["name"])

        artifact = {
            "artifact_type": "live_operator_smoke",
            "ok": not failures,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "storage_engine": "postgres",
            "storage_role": "primary",
            "database_url": run_db_url,
            "maintenance_database_url": maintenance_database_url,
            "root": str(root),
            "port": selected_port,
            "steps": steps,
            "failures": failures,
        }
        if output_path is not None:
            artifact["artifact_path"] = str(output_path)
            _write_json(output_path, artifact)
        return artifact
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
        drop_postgres_database(
            maintenance_database_url=maintenance_database_url,
            db_name=db_name,
        )

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from memco.artifact_semantics import attach_artifact_context
from memco.config import load_settings
from memco.llm import build_llm_provider, llm_runtime_status


REQUIRED_ACTOR_POLICY_CHECKS = {
    "dev-owner": "dev_owner_actor",
    "maintenance-admin": "maintenance_admin_actor",
    "system": "system_actor",
}


def _reason_for_missing(items: dict[str, bool]) -> str:
    missing = [name for name, ok in items.items() if not ok]
    if not missing:
        return "ok"
    return "missing " + ", ".join(missing)


def _actor_policies_step(settings) -> dict[str, Any]:
    actor_policies = settings.api.actor_policies
    checks = {"actor_policies_configured": bool(actor_policies)}
    for actor_id, check_name in REQUIRED_ACTOR_POLICY_CHECKS.items():
        policy = actor_policies.get(actor_id)
        checks[check_name] = bool(policy and (policy.auth_token or "").strip())

    return {
        "name": "actor_policies",
        "ok": all(checks.values()),
        "checks": checks,
        "actor_ids": sorted(actor_policies),
        "actor_types": {actor_id: policy.actor_type for actor_id, policy in sorted(actor_policies.items())},
        "reason": _reason_for_missing(checks),
    }


def run_operator_preflight(*, project_root: Path, postgres_database_url: str | None = None) -> dict[str, Any]:
    settings = load_settings(project_root)
    status = llm_runtime_status(settings)
    runtime_status = status["operator_runtime_status"]
    steps: list[dict[str, Any]] = [
        {
            "name": "config_load",
            "ok": True,
            "root": str(settings.root),
            "config_path": str(settings.config_path),
            "runtime_profile": settings.runtime_profile,
            "storage_engine": settings.storage.engine,
            "database_url_present": bool((settings.storage.database_url or "").strip()),
        },
        {
            "name": "runtime_policy",
            "ok": runtime_status["release_eligible"],
            **status,
            **runtime_status,
        },
    ]

    operator_inputs = {
        "live_llm_credentials": bool(runtime_status["credentials_present"]),
        "llm_base_url": bool(runtime_status["base_url_present"]),
        "api_token": bool((settings.api.auth_token or "").strip()),
        "postgres_storage": settings.storage.engine == "postgres",
        "database_url": bool((settings.storage.database_url or "").strip()),
    }
    steps.append(
        {
            "name": "operator_env",
            "ok": all(operator_inputs.values()),
            "checks": operator_inputs,
            "env_overrides": status["env_overrides"],
            "reason": _reason_for_missing(operator_inputs),
        }
    )
    steps.append(_actor_policies_step(settings))

    backup_exists = settings.backup_path.exists()
    steps.append(
        {
            "name": "backup_path",
            "ok": backup_exists,
            "backup_path": str(settings.backup_path),
            "reason": "ok" if backup_exists else "backup path does not exist",
        }
    )

    db_url = postgres_database_url or settings.storage.database_url
    if not (db_url or "").strip():
        db_step = {
            "name": "db_reachability",
            "ok": False,
            "database_url_source": "missing",
            "reason": "database_url is missing",
        }
    else:
        try:
            with psycopg.connect(db_url, connect_timeout=2) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            db_step = {
                "name": "db_reachability",
                "ok": True,
                "database_url_source": "argument" if postgres_database_url else "settings",
                "reason": "ok",
            }
        except Exception as exc:
            db_step = {
                "name": "db_reachability",
                "ok": False,
                "database_url_source": "argument" if postgres_database_url else "settings",
                "reason": f"{type(exc).__name__}: {exc}",
            }
    steps.append(db_step)

    if not runtime_status["release_eligible"]:
        provider_step = {
            "name": "provider_reachability",
            "ok": False,
            "skipped": True,
            "reason": "runtime_policy_failed",
        }
    else:
        try:
            provider = build_llm_provider(settings)
            response = provider.complete_text(
                system_prompt="Memco operator preflight.",
                prompt='Reply with "ok" if this provider is reachable.',
                metadata={"operation": "operator_preflight"},
            )
            provider_step = {
                "name": "provider_reachability",
                "ok": True,
                "provider": provider.name,
                "model": provider.model,
                "response_preview": response.text[:40],
                "reason": "ok",
            }
        except Exception as exc:
            provider_step = {
                "name": "provider_reachability",
                "ok": False,
                "provider": runtime_status["provider"],
                "model": runtime_status["model"],
                "reason": f"{type(exc).__name__}: {exc}",
            }
    steps.append(provider_step)

    payload = {
        "artifact_type": "operator_preflight",
        "ok": all(step["ok"] for step in steps),
        "project_root": str(project_root),
        "steps": steps,
    }
    return attach_artifact_context(payload, project_root=project_root, steps=steps)

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from shlex import quote
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

import typer

from memco.api.deps import build_internal_actor
from memco.artifact_semantics import attach_artifact_context, evaluate_artifact_freshness
from memco.config import SQLITE_FALLBACK_ENGINE, Settings, load_settings, write_settings
from memco.db import get_connection
from memco.models.candidate import CandidateListRequest
from memco.models.conversation import ConversationImportRequest
from memco.models.fact import FactListRequest
from memco.models.memory_fact import (
    MemoryFactInput,
    PersonAliasUpsertRequest,
    PersonMergeRequest,
    PersonUpsertRequest,
)
from memco.models.person import PersonListRequest
from memco.models.retrieval import RetrievalRequest
from memco.runtime import ensure_runtime
from memco.services.candidate_service import CandidateService
from memco.services.consolidation_service import ConsolidationService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.ingest_service import IngestService
from memco.services.extraction_service import ExtractionService
from memco.services.publish_service import PublishService
from memco.services.eval_service import EvalService
from memco.services.explorer_service import MemoryExplorerService
from memco.services.export_service import ExportService
from memco.services.backup_service import BackupService
from memco.services.chat_runtime import build_chat_services
from memco.services.review_service import ReviewService
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.retrieval_log_repository import RetrievalLogRepository
from memco.postgres_smoke import run_postgres_smoke
from memco.postgres_admin import ensure_postgres_database
from memco.local_artifacts import refresh_local_artifacts
from memco.operator_preflight import run_operator_preflight
from memco.release_check import resolve_repo_project_root, run_release_check, run_release_readiness_check, run_strict_release_check
from memco.services.pipeline_service import IngestPipelineService

app = typer.Typer(help="Memco structured persona-memory CLI.")
eval_app = typer.Typer(help="Evaluation commands.")
app.add_typer(eval_app, name="eval")
backup_app = typer.Typer(help="Backup, export, verification, and restore dry-run commands.")
app.add_typer(backup_app, name="backup")
review_app = typer.Typer(help="Short review queue commands.")
app.add_typer(review_app, name="review")

IMPORT_SOURCE_SHORTCUTS = {"whatsapp", "telegram", "pdf", "note"}


def _settings(root: str | None) -> Settings:
    settings = load_settings(root)
    ensure_runtime(settings)
    return settings


def _eval_settings(root: str | None) -> Settings:
    settings = load_settings(root)
    if settings.config_path.exists():
        if settings.runtime.profile != "fixture" or settings.storage.engine != SQLITE_FALLBACK_ENGINE:
            raise typer.BadParameter(
                "eval-run requires an empty root or an existing fixture/sqlite eval root; "
                "do not point it at a live repo/runtime root."
            )
    else:
        settings.runtime.profile = "fixture"
        settings.storage.engine = SQLITE_FALLBACK_ENGINE
        write_settings(settings)
    ensure_runtime(settings)
    return settings


def _project_root(project_root: str | None) -> Path:
    selected = Path(project_root).expanduser().resolve() if project_root else Path.cwd().resolve()
    try:
        return resolve_repo_project_root(selected)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _emit_json_artifact(payload: dict, *, output: str | None) -> None:
    final_payload = dict(payload)
    if output:
        output_path = Path(output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final_payload["artifact_path"] = str(output_path)
        output_path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(json.dumps(final_payload, ensure_ascii=False, indent=2))


def _redact_database_target(value: str) -> str:
    if "://" not in value:
        return value
    parts = urlsplit(value)
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"***@{hostname}{port}" if parts.username or parts.password else f"{hostname}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _doctor_report(project_root: Path) -> dict:
    settings = load_settings(project_root)
    personal_goldens = project_root / "eval" / "personal_memory_goldens"
    realistic_goldens = personal_goldens / "realistic_personal_memory_goldens.jsonl"
    repo_local = settings.runtime_profile == "repo-local"
    checks = {
        "config_exists": settings.config_path.exists(),
        "api_token_configured": bool((settings.api.auth_token or "").strip()),
        "backup_path_exists": settings.backup_path.exists(),
        "personal_memory_goldens_exist": personal_goldens.is_dir(),
        "realistic_personal_memory_goldens_exist": realistic_goldens.exists(),
        "postgres_url_configured": bool((settings.storage.database_url or "").strip()),
        "owner_configured": bool((settings.owner.person_slug or "").strip() or (settings.owner.display_name or "").strip()),
        "live_smoke_available": bool((settings.storage.database_url or "").strip())
        and os.environ.get("MEMCO_RUN_LIVE_SMOKE", "").strip().lower() in {"1", "true", "yes", "on"},
    }
    ok = (
        checks["personal_memory_goldens_exist"]
        and checks["realistic_personal_memory_goldens_exist"]
        and (not repo_local or checks["api_token_configured"])
        and (not repo_local or checks["backup_path_exists"])
    )
    return {
        "artifact_type": "doctor_report",
        "ok": ok,
        "project_root": str(project_root),
        "config_path": str(settings.config_path),
        "runtime_profile": settings.runtime_profile,
        "storage": {
            "engine": settings.storage.engine,
            "contract_engine": settings.storage.contract_engine,
            "role": settings.storage_role,
            "database_target": _redact_database_target(settings.database_target),
            "backup_path": str(settings.backup_path),
        },
        "llm": {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "base_url": _redact_database_target(settings.llm.base_url),
            "api_key_configured": bool((settings.llm.api_key or "").strip()),
            "allow_mock_provider": settings.llm.allow_mock_provider,
        },
        "api": {
            "auth_token_configured": checks["api_token_configured"],
            "require_actor_scope": settings.api.require_actor_scope,
            "actor_policy_count": len(settings.api.actor_policies),
        },
        "owner": {
            "person_slug_configured": bool((settings.owner.person_slug or "").strip()),
            "display_name_configured": bool((settings.owner.display_name or "").strip()),
        },
        "live_smoke": {
            "available": checks["live_smoke_available"],
            "requested": os.environ.get("MEMCO_RUN_LIVE_SMOKE", "").strip().lower() in {"1", "true", "yes", "on"},
            "postgres_url_configured": checks["postgres_url_configured"],
        },
        "checks": checks,
        "next_commands": {
            "fixture_personal_memory_eval": "uv run memco eval personal-memory --goldens eval/personal_memory_goldens --output var/reports/personal-memory-eval-current.json",
            "fixture_gate": "uv run memco release-check --project-root . --fixture-ok --include-realistic-eval --output var/reports/release-check-fixture-current.json",
            "repo_local_gate": "uv run memco release-check --project-root . --include-realistic-eval --output var/reports/release-check-current.json",
            "release_grade_gate": "MEMCO_RUN_LIVE_SMOKE=1 uv run memco release-readiness-check --project-root . --postgres-database-url \"$MEMCO_POSTGRES_DATABASE_URL\" --require-live-provider --require-postgres --output var/reports/release-readiness-check-current.json",
        },
    }


def _backup_passphrase(*, encrypted_or_required: bool, passphrase_env: str | None) -> str | None:
    env_name = passphrase_env or "MEMCO_BACKUP_PASSPHRASE"
    value = os.environ.get(env_name)
    if encrypted_or_required and not value:
        raise typer.BadParameter(f"{env_name} must be set for encrypted backup operations.")
    return value


def _owner_display_name(owner: str) -> str:
    parts = owner.replace("_", " ").replace("-", " ").split()
    return " ".join(part[:1].upper() + part[1:] for part in parts) or owner


def _next_operator_commands(*, source_id: int, root: str | None) -> dict:
    root_suffix = f" --root {root}" if root else ""
    return {
        "conversation_import": f"memco conversation-import {source_id}{root_suffix}",
        "candidate_extract": f"memco candidate-extract --latest-conversation{root_suffix}",
        "review_pending": f"memco review pending{root_suffix}",
        "publish_all_safe": f"memco publish --all-safe{root_suffix}",
    }


def _resolve_import_shortcut(
    *,
    path: str,
    extra_args: list[str],
    source_type: str,
) -> tuple[str, str, str]:
    if path in IMPORT_SOURCE_SHORTCUTS:
        if not extra_args:
            return path, source_type, "legacy"
        if len(extra_args) > 1:
            raise typer.BadParameter("Import shortcuts accept exactly one path argument.")
        if source_type not in {"note", path}:
            raise typer.BadParameter("Use either an import shortcut or --source-type, not both.")
        return extra_args[0], path, f"import_{path}_shortcut"
    if extra_args:
        raise typer.BadParameter(f"Unexpected extra import argument: {extra_args[0]}")
    return path, source_type, "legacy"


def _resolve_cli_id(
    *,
    explicit_id: int | None,
    latest: bool,
    id_label: str,
    latest_label: str,
    resolver,
) -> int:
    if explicit_id is not None and latest:
        raise typer.BadParameter(f"Use either {id_label} or {latest_label}, not both.")
    if explicit_id is not None:
        return int(explicit_id)
    if latest:
        resolved = resolver()
        if resolved is None:
            raise typer.BadParameter(f"No {id_label} found for {latest_label}.")
        return int(resolved)
    raise typer.BadParameter(f"{id_label} is required unless {latest_label} is set.")


def _latest_source_id(conn, *, workspace_slug: str) -> int | None:
    row = conn.execute(
        """
        SELECT s.id
        FROM sources s
        JOIN workspaces w ON w.id = s.workspace_id
        WHERE w.slug = ?
        ORDER BY s.id DESC
        LIMIT 1
        """,
        (workspace_slug,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _latest_conversation_id(conn, *, workspace_slug: str) -> int | None:
    row = conn.execute(
        """
        SELECT c.id
        FROM conversations c
        JOIN workspaces w ON w.id = c.workspace_id
        WHERE w.slug = ?
        ORDER BY c.id DESC
        LIMIT 1
        """,
        (workspace_slug,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _latest_candidate_id(
    conn,
    *,
    workspace_slug: str,
    person_id: int | None = None,
    candidate_status: str | None = None,
    domain: str | None = None,
) -> int | None:
    sql = """
        SELECT fc.id
        FROM fact_candidates fc
        JOIN workspaces w ON w.id = fc.workspace_id
        WHERE w.slug = ?
    """
    params: list[object] = [workspace_slug]
    if person_id is not None:
        sql += " AND fc.person_id = ?"
        params.append(person_id)
    if candidate_status:
        sql += " AND fc.candidate_status = ?"
        params.append(candidate_status)
    if domain:
        sql += " AND fc.domain = ?"
        params.append(domain)
    sql += " ORDER BY fc.id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return int(row["id"]) if row is not None else None


def _latest_fact_id(
    conn,
    *,
    workspace_slug: str,
    person_id: int | None = None,
    status: str | None = None,
    domain: str | None = None,
) -> int | None:
    repository = FactRepository()
    workspace_id = repository.ensure_workspace(conn, workspace_slug)
    sql = "SELECT id FROM memory_facts WHERE workspace_id = ?"
    params: list[object] = [workspace_id]
    if person_id is not None:
        sql += " AND person_id = ?"
        params.append(person_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    sql += " ORDER BY id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return int(row["id"]) if row is not None else None


def _latest_operation_id(
    conn,
    *,
    workspace_slug: str,
    person_id: int | None = None,
    target_fact_id: int | None = None,
    operation_type: str | None = None,
) -> int | None:
    repository = FactRepository()
    operations = repository.list_operations(
        conn,
        workspace_slug=workspace_slug,
        person_id=person_id,
        target_fact_id=target_fact_id,
        operation_type=operation_type,
        limit=1,
    )
    return int(operations[0]["id"]) if operations else None


def _latest_review_id(
    conn,
    *,
    workspace_slug: str,
    status: str | None = None,
    person_id: int | None = None,
) -> int | None:
    service = ReviewService()
    items = service.list_items(
        conn,
        workspace_slug=workspace_slug,
        status=status,
        person_id=person_id,
        limit=1,
    )
    return int(items[0]["id"]) if items else None


def _resolve_person_option(
    *,
    conn,
    workspace_slug: str,
    person_id: int | None,
    person_slug: str | None,
    option_name: str,
) -> int | None:
    if person_id is not None and person_slug is not None:
        raise typer.BadParameter(f"Use either {option_name}-id or {option_name}-slug, not both.")
    if person_id is not None:
        return int(person_id)
    if person_slug is not None:
        repository = FactRepository()
        try:
            return repository.resolve_person_id(conn, workspace_slug=workspace_slug, person_slug=person_slug)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    return None


@app.command("init-db", help="Initialize the local runtime and database. Next step: `person-upsert`.")
def init_db(root: str | None = typer.Option(None, help="Project root.")) -> None:
    settings = _settings(root)
    typer.echo(f"Runtime ready at {settings.root}")
    typer.echo(f"Storage contract: {settings.storage_contract}")
    typer.echo(f"Storage role: {settings.storage_role}")
    typer.echo(f"Storage engine: {settings.storage.engine}")
    typer.echo(f"Database ready at {settings.database_target}")


@app.command("doctor", help="Print a redacted local runtime and release-gate preflight report.")
def doctor_command(
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    output: str | None = typer.Option(None, help="Optional file path to save the doctor report JSON."),
) -> None:
    resolved_project_root = _project_root(project_root)
    result = _doctor_report(resolved_project_root)
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command(
    "verify-current-status",
    help="Validate docs/CURRENT_STATUS.md against fresh local proof and current artifact freshness.",
)
def verify_current_status_command(
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    pytest_passed: int | None = typer.Option(None, help="Fresh pytest passed count to compare with docs/CURRENT_STATUS.md."),
    output: str | None = typer.Option(None, help="Optional file path to save the verification artifact JSON."),
) -> None:
    resolved_project_root = _project_root(project_root)
    status_path = resolved_project_root / "docs" / "CURRENT_STATUS.md"
    reports_dir = resolved_project_root / "var" / "reports"
    status_text = status_path.read_text(encoding="utf-8") if status_path.exists() else ""
    checks: list[dict] = [
        {"name": "current_status_exists", "ok": status_path.exists(), "path": str(status_path)},
        {
            "name": "current_status_points_to_reproduction",
            "ok": all(marker in status_text for marker in ("LOCAL_REPRODUCTION.md", "Fresh gate evidence", "uv run pytest -q")),
        },
    ]
    pytest_match = re.search(r"`uv run pytest -q`:\s*(?P<count>\d+)\s+passed", status_text)
    documented_pytest_passed = int(pytest_match.group("count")) if pytest_match else None
    checks.append(
        {
            "name": "pytest_count_matches_fresh_input",
            "ok": pytest_passed is None or documented_pytest_passed == pytest_passed,
            "documented": documented_pytest_passed,
            "fresh": pytest_passed,
            "skipped": pytest_passed is None,
        }
    )
    artifact_reports = []
    artifact_payloads: dict[str, dict] = {}
    for name in (
        "personal-memory-eval-current.json",
        "release-check-current.json",
        "local-artifacts-refresh-current.json",
        "release-readiness-check-current.json",
        "live-operator-smoke-current.json",
    ):
        path = reports_dir / name
        if not path.exists():
            artifact_reports.append({"name": name, "exists": False, "ok": False, "freshness": {"status": "missing"}})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            artifact_payloads[name] = payload
            freshness = evaluate_artifact_freshness(payload, project_root=resolved_project_root)
        except Exception as exc:
            freshness = {"status": "invalid", "reason": str(exc)}
        artifact_reports.append(
            {
                "name": name,
                "exists": True,
                "ok": freshness.get("current_for_checkout_config") is True,
                "freshness": freshness,
            }
        )
    checks.append(
        {
            "name": "current_artifacts_are_fresh",
            "ok": all(item.get("ok") is True for item in artifact_reports),
            "artifacts": artifact_reports,
        }
    )
    personal_eval_match = re.search(
        r"personal-memory-eval-current\.json`:[^\n]*?(?P<passed>\d+)\s*/\s*(?P<total>\d+)\s+passed",
        status_text,
    )
    personal_payload = artifact_payloads.get("personal-memory-eval-current.json", {})
    checks.append(
        {
            "name": "personal_eval_count_matches_status",
            "ok": personal_eval_match is not None
            and personal_payload.get("passed") == int(personal_eval_match.group("passed"))
            and personal_payload.get("total") == int(personal_eval_match.group("total")),
            "documented": (
                {
                    "passed": int(personal_eval_match.group("passed")),
                    "total": int(personal_eval_match.group("total")),
                }
                if personal_eval_match
                else None
            ),
            "artifact": {
                "passed": personal_payload.get("passed"),
                "total": personal_payload.get("total"),
            },
        }
    )
    token_accounting = personal_payload.get("token_accounting", {})
    retrieval_latency = personal_payload.get("retrieval_latency_ms", {})
    checks.append(
        {
            "name": "personal_eval_token_latency_accounting_present",
            "ok": token_accounting.get("implemented") is True
            and token_accounting.get("status") == "tracked"
            and isinstance(retrieval_latency.get("p50"), (int, float))
            and isinstance(retrieval_latency.get("p95"), (int, float)),
            "artifact": {
                "token_accounting_implemented": token_accounting.get("implemented"),
                "token_accounting_status": token_accounting.get("status"),
                "retrieval_latency_p50": retrieval_latency.get("p50"),
                "retrieval_latency_p95": retrieval_latency.get("p95"),
            },
        }
    )
    release_payload = artifact_payloads.get("release-check-current.json", {})
    release_acceptance = None
    for step in release_payload.get("steps", []):
        if step.get("name") == "acceptance_artifact":
            summary = step.get("artifact_summary", {})
            release_acceptance = {"passed": summary.get("passed"), "total": summary.get("total")}
            break
    release_acceptance_match = re.search(
        r"release-check-current\.json`:[^\n]*?acceptance\s+(?P<passed>\d+)\s*/\s*(?P<total>\d+)",
        status_text,
    )
    checks.append(
        {
            "name": "release_check_acceptance_matches_status",
            "ok": release_acceptance_match is not None
            and release_acceptance == {
                "passed": int(release_acceptance_match.group("passed")),
                "total": int(release_acceptance_match.group("total")),
            },
            "documented": (
                {
                    "passed": int(release_acceptance_match.group("passed")),
                    "total": int(release_acceptance_match.group("total")),
                }
                if release_acceptance_match
                else None
            ),
            "artifact": release_acceptance,
        }
    )
    local_refresh_payload = artifact_payloads.get("local-artifacts-refresh-current.json", {})
    local_summaries = local_refresh_payload.get("summaries", {})
    local_refresh_match = re.search(
        r"local-artifacts-refresh-current\.json`:[^\n]*?"
        r"full suite\s+(?P<full>\d+)\s+passed,\s+"
        r"contract stack\s+(?P<contract>\d+)\s+passed,\s+"
        r"release-check acceptance\s+(?P<acceptance_passed>\d+)\s*/\s*(?P<acceptance_total>\d+)",
        status_text,
    )
    expected_full = f"{local_refresh_match.group('full')} passed" if local_refresh_match else None
    expected_contract = f"{local_refresh_match.group('contract')} passed" if local_refresh_match else None
    expected_acceptance = (
        f"{local_refresh_match.group('acceptance_passed')}/{local_refresh_match.group('acceptance_total')}"
        if local_refresh_match
        else None
    )
    checks.append(
        {
            "name": "local_artifacts_refresh_summary_matches_status",
            "ok": local_refresh_match is not None
            and str(local_summaries.get("full_suite", "")).startswith(expected_full or "")
            and str(local_summaries.get("contract_stack", "")).startswith(expected_contract or "")
            and local_summaries.get("release_check_acceptance") == expected_acceptance,
            "documented": (
                {
                    "full_suite": expected_full,
                    "contract_stack": expected_contract,
                    "release_check_acceptance": expected_acceptance,
                }
                if local_refresh_match
                else None
            ),
            "artifact": {
                "full_suite": local_summaries.get("full_suite"),
                "contract_stack": local_summaries.get("contract_stack"),
                "release_check_acceptance": local_summaries.get("release_check_acceptance"),
            },
        }
    )
    release_grade_claimed = (
        local_summaries.get("release_check_postgres_gate_type") is not None
        or local_summaries.get("strict_release_check_gate_type") is not None
        or local_summaries.get("live_operator_smoke_current") is not None
    )
    release_grade_claim_ok = (
        local_summaries.get("release_check_postgres_gate_type") == "canonical-postgres"
        and local_summaries.get("strict_release_check_gate_type") == "strict-quality"
        and local_summaries.get("live_operator_smoke_current") is True
    )
    checks.append(
        {
            "name": "local_refresh_release_grade_claims_are_consistent",
            "ok": release_grade_claim_ok if release_grade_claimed else True,
            "artifact": {
                "release_check_postgres_gate_type": local_summaries.get("release_check_postgres_gate_type"),
                "strict_release_check_gate_type": local_summaries.get("strict_release_check_gate_type"),
                "live_operator_smoke_current": local_summaries.get("live_operator_smoke_current"),
            },
        }
    )
    result = {
        "artifact_type": "current_status_verification",
        "project_root": str(resolved_project_root),
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command(
    "import",
    help="Import a source file into the workspace. Shortcuts: `import whatsapp PATH`, `import telegram PATH`, `import pdf PATH`, `import note PATH --owner martin`. For conversations, next step: `conversation-import SOURCE_ID`.",
    context_settings={"allow_extra_args": True},
)
def import_command(
    ctx: typer.Context,
    path: str,
    source_type: str = typer.Option("note", help="Source type."),
    owner: str | None = typer.Option(None, help="Optional owner slug/display name to upsert for note-style imports."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    resolved_path, resolved_source_type, command_shape = _resolve_import_shortcut(
        path=path,
        extra_args=list(ctx.args),
        source_type=source_type,
    )
    settings = _settings(root)
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug=workspace,
            path=Path(resolved_path),
            source_type=resolved_source_type,
        )
        payload = result.model_dump(mode="json")
        payload["command_shape"] = command_shape
        payload["next_commands"] = _next_operator_commands(source_id=result.source_id, root=root)
        if owner:
            owner_person = FactRepository().upsert_person(
                conn,
                workspace_slug=workspace,
                display_name=_owner_display_name(owner),
                slug=owner,
                person_type="human",
                aliases=[owner],
            )
            payload["owner"] = {
                "person_id": int(owner_person["id"]),
                "slug": owner_person["slug"],
                "display_name": owner_person["display_name"],
            }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command(
    "ingest-pipeline",
    help="One-shot private operator flow: optional person upsert, import, conversation import, candidate extract, auto-publish validated candidates, and report pending review items. Intended for one-time loading before API/Hermes use.",
)
def ingest_pipeline_command(
    path: str,
    source_type: str = typer.Option("json", help="Source type."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_display_name: str | None = typer.Option(None, help="Optional person display name to upsert before import."),
    person_slug: str | None = typer.Option(None, help="Optional person slug for the upsert step."),
    alias: list[str] = typer.Option(None, "--alias", help="Alias for the optional person upsert. Can be repeated."),
    conversation_uid: str = typer.Option("main", help="Stable conversation uid."),
    title: str = typer.Option("", help="Conversation title override."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = IngestPipelineService()

    if (person_slug or alias) and not person_display_name:
        raise typer.BadParameter("--person-display-name is required when using --person-slug or --alias")

    with get_connection(settings.db_path) as conn:
        result = service.ingest_path(
            settings,
            conn,
            workspace_slug=workspace,
            path=Path(path),
            source_type=source_type,
            person_display_name=person_display_name,
            person_slug=person_slug,
            aliases=alias or [],
            conversation_uid=conversation_uid,
            title=title,
        )

    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "person-upsert",
    help="Create or update a person record. Next step: `import PATH` for a source tied to that person.",
)
def person_upsert_command(
    display_name: str,
    workspace: str = typer.Option("default", help="Workspace slug."),
    slug: str | None = typer.Option(None, help="Stable person slug."),
    person_type: str = typer.Option("human", help="Person type."),
    alias: list[str] = typer.Option(None, "--alias", help="Alias. Can be repeated."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    payload = PersonUpsertRequest(
        workspace=workspace,
        display_name=display_name,
        slug=slug,
        person_type=person_type,
        aliases=alias or [],
    )
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        result = repository.upsert_person(
            conn,
            workspace_slug=payload.workspace,
            display_name=payload.display_name,
            slug=payload.slug,
            person_type=payload.person_type,
            aliases=payload.aliases,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("person-list", help="List persons in the workspace. Often used before `person-alias-upsert` or `person-merge`.")
def person_list_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    status: str | None = typer.Option(None, help="Status filter."),
    limit: int = typer.Option(100, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = FactRepository()
    payload = PersonListRequest(workspace=workspace, status=status, limit=limit)
    with get_connection(settings.db_path) as conn:
        result = repository.list_persons(
            conn,
            workspace_slug=payload.workspace,
            status=payload.status,
            limit=payload.limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "person-alias-upsert",
    help="Attach or update an alias for a person. Next step: `conversation-speaker-resolve` or `candidate-extract`.",
)
def person_alias_upsert_command(
    alias: str,
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Existing person id."),
    person_slug: str | None = typer.Option(None, help="Existing person slug."),
    alias_type: str = typer.Option("name", help="Alias type."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = FactRepository()
    payload = PersonAliasUpsertRequest(
        workspace=workspace,
        person_id=person_id,
        person_slug=person_slug,
        alias=alias,
        alias_type=alias_type,
    )
    with get_connection(settings.db_path) as conn:
        resolved_person_id = payload.person_id
        if resolved_person_id is None:
            resolved_person_id = repository.resolve_person_id(
                conn,
                workspace_slug=payload.workspace,
                person_slug=payload.person_slug,
            )
        result = repository.upsert_person_alias(
            conn,
            workspace_slug=payload.workspace,
            person_id=int(resolved_person_id),
            alias=payload.alias,
            alias_type=payload.alias_type,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("person-merge", help="Merge duplicate person records. Next step: `person-list`, `candidate-list`, or `retrieve`.")
def person_merge_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    from_person_id: int | None = typer.Option(None, help="Source person id."),
    from_person_slug: str | None = typer.Option(None, help="Source person slug."),
    to_person_id: int | None = typer.Option(None, help="Target person id."),
    to_person_slug: str | None = typer.Option(None, help="Target person slug."),
    reason: str = typer.Option("", help="Merge reason."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = FactRepository()
    payload = PersonMergeRequest(
        workspace=workspace,
        from_person_id=from_person_id,
        from_person_slug=from_person_slug,
        to_person_id=to_person_id,
        to_person_slug=to_person_slug,
        reason=reason,
    )
    with get_connection(settings.db_path) as conn:
        resolved_from = payload.from_person_id
        if resolved_from is None:
            resolved_from = repository.resolve_person_id(
                conn,
                workspace_slug=payload.workspace,
                person_slug=payload.from_person_slug,
            )
        resolved_to = payload.to_person_id
        if resolved_to is None:
            resolved_to = repository.resolve_person_id(
                conn,
                workspace_slug=payload.workspace,
                person_slug=payload.to_person_slug,
            )
        result = repository.merge_persons(
            conn,
            workspace_slug=payload.workspace,
            from_person_id=int(resolved_from),
            to_person_id=int(resolved_to),
            reason=payload.reason,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "fact-add",
    help="Manually add a fact to the truth store. Next step: `retrieve`, `chat`, or `fact-operations`. Omit SOURCE_ID with `--latest-source` in simple single-user flows.",
)
def fact_add_command(
    person_slug: str,
    domain: str,
    category: str,
    canonical_key: str,
    observed_at: str,
    source_id: int | None = typer.Argument(None, help="Source id. Omit with `--latest-source`."),
    latest_source: bool = typer.Option(False, help="Use the most recently imported source in the workspace."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    subcategory: str = typer.Option("", help="Subcategory."),
    summary: str = typer.Option("", help="Human summary."),
    payload_json: str = typer.Option("{}", help="JSON payload."),
    confidence: float = typer.Option(0.5, help="Confidence."),
    quote_text: str = typer.Option("", help="Supporting quote."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        resolved_source_id = _resolve_cli_id(
            explicit_id=source_id,
            latest=latest_source,
            id_label="source_id",
            latest_label="--latest-source",
            resolver=lambda: _latest_source_id(conn, workspace_slug=workspace),
        )
        payload = MemoryFactInput(
            workspace=workspace,
            person_slug=person_slug,
            domain=domain,
            category=category,
            subcategory=subcategory,
            canonical_key=canonical_key,
            payload=json.loads(payload_json),
            summary=summary,
            confidence=confidence,
            observed_at=observed_at,
            source_id=resolved_source_id,
            quote_text=quote_text,
        )
        result = service.add_fact(conn, payload)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("retrieve", help="Retrieve supported facts for a person. Often used after `candidate-publish` or `fact-rollback`.")
def retrieve_command(
    query: str,
    person_slug: str,
    workspace: str = typer.Option("default", help="Workspace slug."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    temporal_mode: str = typer.Option("auto", help="Temporal mode: auto/current/history."),
    detail_policy: str = typer.Option("balanced", help="Detail policy: core_only|balanced|exhaustive."),
    limit: int = typer.Option(8, help="Hit limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service, _answer_service = build_chat_services(settings)
    actor = build_internal_actor(settings, actor_id="dev-owner")
    payload = RetrievalRequest(
        workspace=workspace,
        person_slug=person_slug,
        query=query,
        domain=domain,
        temporal_mode=temporal_mode,
        detail_policy=detail_policy,
        limit=limit,
        include_fallback=True,
        actor=actor,
    )
    with get_connection(settings.db_path) as conn:
        result = service.retrieve(conn, payload, settings=settings, route_name="retrieve")
    typer.echo(json.dumps(service.present_result(result, detail_policy=payload.detail_policy), ensure_ascii=False, indent=2))


@app.command("chat", help="Answer from confirmed memory and refuse unsupported claims. Often used after `retrieve`.")
def chat_command(
    query: str,
    person_slug: str,
    workspace: str = typer.Option("default", help="Workspace slug."),
    temporal_mode: str = typer.Option("auto", help="Temporal mode: auto/current/history."),
    detail_policy: str = typer.Option("balanced", help="Detail policy: core_only|balanced|exhaustive."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    retrieval_service, answer_service = build_chat_services(settings)
    actor = build_internal_actor(settings, actor_id="dev-owner")
    payload = RetrievalRequest(
        workspace=workspace,
        person_slug=person_slug,
        query=query,
        temporal_mode=temporal_mode,
        detail_policy=detail_policy,
        actor=actor,
    )
    with get_connection(settings.db_path) as conn:
        retrieval = retrieval_service.retrieve(conn, payload, settings=settings, route_name="chat")
    answer = answer_service.build_answer(query=query, retrieval_result=retrieval, detail_policy=payload.detail_policy)
    typer.echo(json.dumps({"query": query, "retrieval": retrieval_service.present_result(retrieval, detail_policy=payload.detail_policy), **answer}, ensure_ascii=False, indent=2))


@app.command(
    "conversation-import",
    help="Parse an imported source into a conversation. Next step: `candidate-extract CONVERSATION_ID` or `candidate-extract --latest-conversation`.",
)
def conversation_import_command(
    source_id: int | None = typer.Argument(None, help="Source id. Omit with `--latest-source`."),
    latest_source: bool = typer.Option(False, help="Use the most recently imported source in the workspace."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    conversation_uid: str = typer.Option("main", help="Stable conversation uid."),
    title: str = typer.Option("", help="Conversation title override."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ConversationIngestService()
    payload = ConversationImportRequest(
        workspace=workspace,
        source_id=0,
        conversation_uid=conversation_uid,
        title=title,
    )
    with get_connection(settings.db_path) as conn:
        resolved_source_id = _resolve_cli_id(
            explicit_id=source_id,
            latest=latest_source,
            id_label="source_id",
            latest_label="--latest-source",
            resolver=lambda: _latest_source_id(conn, workspace_slug=workspace),
        )
        result = service.import_conversation(
            settings,
            conn,
            workspace_slug=payload.workspace,
            source_id=resolved_source_id,
            conversation_uid=payload.conversation_uid,
            title=payload.title,
        )
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command(
    "candidate-extract",
    help="Extract candidates from a conversation. Next step: `candidate-list` and then `candidate-publish`, `candidate-publish --latest-candidate`, `candidate-reject`, or `review-list`.",
)
def candidate_extract_command(
    conversation_id: int | None = typer.Argument(None, help="Conversation id. Omit with `--latest-conversation`."),
    latest_conversation: bool = typer.Option(False, help="Use the most recently imported conversation in the workspace."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = CandidateService(extraction_service=ExtractionService.from_settings(settings))
    with get_connection(settings.db_path) as conn:
        resolved_conversation_id = _resolve_cli_id(
            explicit_id=conversation_id,
            latest=latest_conversation,
            id_label="conversation_id",
            latest_label="--latest-conversation",
            resolver=lambda: _latest_conversation_id(conn, workspace_slug=workspace),
        )
        result = service.extract_from_conversation(
            conn,
            workspace_slug=workspace,
            conversation_id=resolved_conversation_id,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "conversation-speakers",
    help="Inspect conversation speaker resolution state. Next step: `conversation-speaker-resolve` or `candidate-extract`.",
)
def conversation_speakers_command(
    conversation_id: int | None = typer.Argument(None, help="Conversation id. Omit with `--latest-conversation`."),
    latest_conversation: bool = typer.Option(False, help="Use the most recently imported conversation in the workspace."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ConversationIngestService()
    with get_connection(settings.db_path) as conn:
        resolved_conversation_id = _resolve_cli_id(
            explicit_id=conversation_id,
            latest=latest_conversation,
            id_label="conversation_id",
            latest_label="--latest-conversation",
            resolver=lambda: _latest_conversation_id(conn, workspace_slug=workspace),
        )
        result = service.list_speakers(conn, conversation_id=resolved_conversation_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "conversation-speaker-resolve",
    help="Resolve a conversation speaker to a person. Next step: `candidate-extract CONVERSATION_ID` or `candidate-extract --latest-conversation`.",
)
def conversation_speaker_resolve_command(
    speaker_key: str,
    conversation_id: int | None = typer.Argument(None, help="Conversation id. Omit with `--latest-conversation`."),
    latest_conversation: bool = typer.Option(False, help="Use the most recently imported conversation in the workspace."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Existing person id."),
    person_slug: str | None = typer.Option(None, help="Existing person slug."),
    create_person_display_name: str | None = typer.Option(None, help="Create person with this display name."),
    create_person_slug: str | None = typer.Option(None, help="Optional slug for created person."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    conversation_service = ConversationIngestService()
    candidate_service = CandidateService(extraction_service=ExtractionService.from_settings(settings))
    with get_connection(settings.db_path) as conn:
        resolved_conversation_id = _resolve_cli_id(
            explicit_id=conversation_id,
            latest=latest_conversation,
            id_label="conversation_id",
            latest_label="--latest-conversation",
            resolver=lambda: _latest_conversation_id(conn, workspace_slug=workspace),
        )
        mapping = conversation_service.resolve_speaker(
            conn,
            workspace_slug=workspace,
            conversation_id=resolved_conversation_id,
            speaker_key=speaker_key,
            person_id=person_id,
            person_slug=person_slug,
            create_person_display_name=create_person_display_name,
            create_person_slug=create_person_slug,
        )
        candidates = candidate_service.reextract_for_speaker_resolution(
            conn,
            workspace_slug=workspace,
            conversation_id=resolved_conversation_id,
        )
    typer.echo(json.dumps({"mapping": mapping, "candidates": candidates}, ensure_ascii=False, indent=2))


@app.command(
    "candidate-list",
    help="List extracted candidates. Next step: `candidate-publish`, `candidate-reject`, or `review-resolve`.",
)
def candidate_list_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    candidate_status: str | None = typer.Option(None, help="Candidate status filter."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    limit: int = typer.Option(20, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = CandidateService()
    payload = CandidateListRequest(
        workspace=workspace,
        person_id=None,
        candidate_status=candidate_status,
        domain=domain,
        limit=limit,
    )
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = service.list_candidates(
            conn,
            workspace_slug=payload.workspace,
            person_id=resolved_person_id,
            candidate_status=payload.candidate_status,
            domain=payload.domain,
            limit=payload.limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "candidate-publish",
    help="Promote a candidate into the fact store. Next step: `retrieve`, `chat`, or `fact-operations`. Omit CANDIDATE_ID with `--latest-candidate` to target the newest matching candidate in the current scope; this command fails closed if that newest candidate is not publishable.",
)
def candidate_publish_command(
    candidate_id: int | None = typer.Argument(None, help="Candidate id. Omit with `--latest-candidate`."),
    latest_candidate: bool = typer.Option(
        False,
        help="Use the newest matching candidate in the current scope. Combine with `--person-slug` and/or `--domain` to avoid workspace-wide ambiguity. If it is not publishable, the command fails closed.",
    ),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter for `--latest-candidate`."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter for `--latest-candidate`."),
    domain: str | None = typer.Option(None, help="Optional domain filter for `--latest-candidate`."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = PublishService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_candidate_id = _resolve_cli_id(
            explicit_id=candidate_id,
            latest=latest_candidate,
            id_label="candidate_id",
            latest_label="--latest-candidate",
            resolver=lambda: _latest_candidate_id(
                conn,
                workspace_slug=workspace,
                person_id=resolved_person_id,
                domain=domain,
            ),
        )
        try:
            result = service.publish_candidate(
                conn,
                workspace_slug=workspace,
                candidate_id=resolved_candidate_id,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "publish",
    help="Bulk publish validated candidates that pass the normal safe publish checks. Use `publish --all-safe`; review uncertain items first with `review pending`.",
)
def publish_command(
    all_safe: bool = typer.Option(False, "--all-safe", help="Publish every currently validated candidate that passes publish safety checks."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter."),
    domain: str | None = typer.Option(None, help="Optional domain filter."),
    limit: int = typer.Option(100, help="Maximum validated candidates to inspect."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    if not all_safe:
        raise typer.BadParameter("Use --all-safe, or use candidate-publish for one explicit candidate.")
    settings = _settings(root)
    candidate_repository = CandidateRepository()
    service = PublishService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        candidates = candidate_repository.list_candidates(
            conn,
            workspace_slug=workspace,
            person_id=resolved_person_id,
            candidate_status="validated_candidate",
            domain=domain,
            limit=limit,
        )
        published: list[dict] = []
        skipped: list[dict] = []
        for candidate in candidates:
            try:
                published.append(
                    service.publish_candidate(
                        conn,
                        workspace_slug=workspace,
                        candidate_id=int(candidate["id"]),
                    )
                )
            except ValueError as exc:
                skipped.append({"candidate_id": int(candidate["id"]), "reason": str(exc)})
    payload = {
        "artifact_type": "publish_all_safe_result",
        "workspace": workspace,
        "filters": {
            "person_id": resolved_person_id,
            "domain": domain,
            "limit": limit,
            "candidate_status": "validated_candidate",
        },
        "counts": {
            "inspected": len(candidates),
            "published": len(published),
            "skipped": len(skipped),
        },
        "published": published,
        "skipped": skipped,
        "next_commands": {
            "review_pending": f"memco review pending --workspace {workspace}",
            "memory_explorer": f"memco memory-explorer --workspace {workspace}",
        },
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command(
    "candidate-reject",
    help="Reject a candidate. Next step: `candidate-list` or `review-list`. Omit CANDIDATE_ID with `--latest-candidate` to target the newest matching candidate in the current scope.",
)
def candidate_reject_command(
    candidate_id: int | None = typer.Argument(None, help="Candidate id. Omit with `--latest-candidate`."),
    latest_candidate: bool = typer.Option(
        False,
        help="Use the newest matching candidate in the current scope. Combine with `--person-slug` and/or `--domain` to avoid workspace-wide ambiguity.",
    ),
    reason: str = typer.Option("", help="Rejection reason."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter for `--latest-candidate`."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter for `--latest-candidate`."),
    domain: str | None = typer.Option(None, help="Optional domain filter for `--latest-candidate`."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = PublishService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_candidate_id = _resolve_cli_id(
            explicit_id=candidate_id,
            latest=latest_candidate,
            id_label="candidate_id",
            latest_label="--latest-candidate",
            resolver=lambda: _latest_candidate_id(
                conn,
                workspace_slug=workspace,
                person_id=resolved_person_id,
                domain=domain,
            ),
        )
        result = service.reject_candidate(
            conn,
            candidate_id=resolved_candidate_id,
            reason=reason,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "review-resolve",
    help="Resolve a review item. Next step: `candidate-publish`, `candidate-list`, or `review-list`. Omit QUEUE_ID with `--latest-review` in simple single-user flows. Use `--publish` to publish an approved candidate in the same step.",
)
def review_resolve_command(
    decision: str,
    queue_id: int | None = typer.Argument(None, help="Review queue id. Omit with `--latest-review`."),
    latest_review: bool = typer.Option(False, help="Use the newest review item in the workspace."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter for `--latest-review`."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter for `--latest-review`."),
    status: str | None = typer.Option("pending", help="Optional status filter for `--latest-review`."),
    candidate_person_id: int | None = typer.Option(None, help="Resolved person id for approved candidate."),
    candidate_person_slug: str | None = typer.Option(None, help="Resolved person slug for approved candidate."),
    candidate_target_person_id: int | None = typer.Option(None, help="Resolved target person id for approved candidate."),
    candidate_target_person_slug: str | None = typer.Option(None, help="Resolved target person slug for approved candidate."),
    publish: bool = typer.Option(False, help="After an approved resolution, immediately publish the candidate in the same step."),
    reason: str = typer.Option("", help="Resolution reason."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ReviewService()
    with get_connection(settings.db_path) as conn:
        resolved_filter_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_queue_id = _resolve_cli_id(
            explicit_id=queue_id,
            latest=latest_review,
            id_label="queue_id",
            latest_label="--latest-review",
            resolver=lambda: _latest_review_id(
                conn,
                workspace_slug=workspace,
                status=status,
                person_id=resolved_filter_person_id,
            ),
        )
        resolved_candidate_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=candidate_person_id,
            person_slug=candidate_person_slug,
            option_name="candidate-person",
        )
        resolved_candidate_target_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=candidate_target_person_id,
            person_slug=candidate_target_person_slug,
            option_name="candidate-target-person",
        )
        result = service.resolve_with_person(
            conn,
            queue_id=resolved_queue_id,
            decision=decision,
            reason=reason,
            candidate_person_id=resolved_candidate_person_id,
            candidate_target_person_id=resolved_candidate_target_person_id,
        )
        if publish:
            if decision != "approved":
                raise typer.BadParameter("--publish requires decision=approved")
            candidate = result.get("candidate")
            if candidate is None:
                raise typer.BadParameter("--publish requires a review item with a candidate")
            publish_service = PublishService()
            try:
                publish_result = publish_service.publish_candidate(
                    conn,
                    workspace_slug=workspace,
                    candidate_id=int(candidate["id"]),
                )
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            result = {"review": {**result, "candidate": publish_result["candidate"]}, "publish": publish_result}
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("review-list", help="List pending review items. Next step: `review-resolve` or `candidate-list`.")
def review_list_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    status: str | None = typer.Option(None, help="Review status filter."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    limit: int = typer.Option(50, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ReviewService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = service.list_items(
            conn,
            workspace_slug=workspace,
            status=status,
            person_id=resolved_person_id,
            domain=domain,
            limit=limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@review_app.command("pending", help="List pending review items. Next step: `review-resolve approved|rejected` or `publish --all-safe`.")
def review_pending_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    limit: int = typer.Option(50, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ReviewService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = service.list_items(
            conn,
            workspace_slug=workspace,
            status="pending",
            person_id=resolved_person_id,
            domain=domain,
            limit=limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "review-dashboard",
    help="Inspect review queue candidates with evidence, risk flags, and consolidation preview. Next step: `review-resolve`, `candidate-publish`, or `candidate-reject`.",
)
def review_dashboard_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    status: str | None = typer.Option("pending", help="Review status filter."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    limit: int = typer.Option(50, help="Result limit."),
    low_confidence_threshold: float = typer.Option(0.6, help="Flag candidates below this confidence."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ReviewService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = service.dashboard(
            conn,
            workspace_slug=workspace,
            status=status,
            person_id=resolved_person_id,
            domain=domain,
            limit=limit,
            low_confidence_threshold=low_confidence_threshold,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("fact-list", help="List facts in the truth store. Often used after `candidate-publish` or `fact-rollback`.")
def fact_list_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    status: str | None = typer.Option(None, help="Fact status filter."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    limit: int = typer.Option(50, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = FactRepository()
    payload = FactListRequest(
        workspace=workspace,
        person_id=None,
        status=status,
        domain=domain,
        limit=limit,
    )
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = repository.list_facts(
            conn,
            workspace_slug=payload.workspace,
            person_id=resolved_person_id,
            status=payload.status,
            domain=payload.domain,
            limit=payload.limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


TIMELINE_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _timeline_temporal_sort_key(*values: str, fact_id: int) -> tuple[int, int, int, int]:
    text = " ".join(value for value in values if value).strip()
    iso_match = re.search(r"\b(?P<year>(?:19|20)\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b", text)
    if iso_match:
        return (int(iso_match.group("year")), int(iso_match.group("month")), int(iso_match.group("day")), fact_id)
    month_match = re.search(
        r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(?P<year>(?:19|20)\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if month_match:
        return (
            int(month_match.group("year")),
            TIMELINE_MONTHS[month_match.group("month").lower()],
            1,
            fact_id,
        )
    year_match = re.search(r"\b(?P<year>(?:19|20)\d{2})\b", text)
    if year_match:
        return (int(year_match.group("year")), 1, 1, fact_id)
    return (9999, 12, 31, fact_id)


@app.command(
    "build-life-timeline",
    help="Build a chronological experience timeline for one person from active event memories.",
)
def build_life_timeline_command(
    person_slug: str = typer.Argument(..., help="Person slug."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    limit: int = typer.Option(100, help="Maximum experience facts to inspect."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        person_id = repository.resolve_person_id(conn, workspace_slug=workspace, person_slug=person_slug)
        facts = repository.list_facts(
            conn,
            workspace_slug=workspace,
            person_id=person_id,
            status="active",
            domain="experiences",
            limit=limit,
        )
    events = []
    for fact in facts:
        if fact.get("category") != "event":
            continue
        payload = fact.get("payload", {})
        temporal_anchor = str(payload.get("temporal_anchor") or fact.get("event_at") or payload.get("date_range") or "").strip()
        events.append(
            {
                "fact_id": int(fact["id"]),
                "event": payload.get("event") or fact.get("summary") or "",
                "event_type": payload.get("event_type") or "life_event",
                "temporal_anchor": temporal_anchor,
                "event_at": fact.get("event_at") or payload.get("event_at") or "",
                "date_range": payload.get("date_range") or "",
                "location": payload.get("location") or "",
                "participants": payload.get("participants") or [],
                "outcome": payload.get("outcome") or "",
                "lesson": payload.get("lesson") or "",
                "salience": payload.get("salience", payload.get("intensity")),
                "summary": fact.get("summary") or payload.get("summary") or "",
                "evidence_ids": [int(item["evidence_id"]) for item in fact.get("evidence", []) if item.get("evidence_id") is not None],
            }
        )
    events.sort(
        key=lambda item: _timeline_temporal_sort_key(
            str(item.get("event_at") or ""),
            str(item.get("temporal_anchor") or ""),
            str(item.get("date_range") or ""),
            fact_id=int(item["fact_id"]),
        )
    )
    result = {
        "artifact_type": "life_timeline",
        "workspace": workspace,
        "person_slug": person_slug,
        "person_id": int(person_id),
        "event_count": len(events),
        "events": events,
    }
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "memory-explorer",
    help="Local memory explorer snapshot: facts with evidence, review candidates, lifecycle changes, rollback hints, and domain filters.",
)
def memory_explorer_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    fact_status: str | None = typer.Option(None, "--fact-status", help="Fact status filter."),
    domain: str | None = typer.Option(None, help="Domain filter."),
    review_status: str | None = typer.Option("pending", help="Review status filter."),
    limit: int = typer.Option(50, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = MemoryExplorerService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = service.snapshot(
            conn,
            workspace_slug=workspace,
            person_id=resolved_person_id,
            fact_status=fact_status,
            domain=domain,
            review_status=review_status,
            limit=limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("persona-export", help="Export one persona as structured JSON without raw source content.")
def persona_export_command(
    person_id: int | None = typer.Option(None, help="Person id."),
    person_slug: str | None = typer.Option(None, help="Person slug."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    domain: str | None = typer.Option(None, help="Optional domain filter."),
    detail_policy: str = typer.Option("balanced", help="Detail policy: core_only|balanced|exhaustive."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ExportService()
    actor = build_internal_actor(settings, actor_id="dev-owner")
    with get_connection(settings.db_path) as conn:
        result = service.export_persona(
            settings,
            conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            domain=domain,
            detail_policy=detail_policy,
            actor=actor,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def _default_backup_output(settings: Settings, *, mode: str, encrypted: bool) -> Path:
    suffix = ".json.enc" if encrypted else ".json"
    stem = "memco-full-backup" if mode == "full" else "memco-audit-export"
    return settings.root / "var" / "backups" / f"{stem}{suffix}"


def _backup_runbook(settings: Settings, *, storage_engine: str | None = None) -> dict:
    engine = (storage_engine or settings.storage.engine).strip().lower()
    if engine not in {"sqlite", "postgres"}:
        raise typer.BadParameter("storage_engine must be sqlite or postgres")
    sqlite_db_path = settings.db_path
    sqlite_backup_path = settings.root / "var" / "backups" / "memco-sqlite.backup"
    postgres_dump_path = settings.backup_path
    audit_json_path = settings.root / "var" / "backups" / "memco-audit-export.json"
    encrypted_json_path = settings.root / "var" / "backups" / "memco-full-backup.json.enc"
    if engine == "sqlite":
        native_backup = {
            "kind": "sqlite_backup",
            "command": f"sqlite3 {quote(str(sqlite_db_path))} \".backup {quote(str(sqlite_backup_path))}\"",
            "output_path": str(sqlite_backup_path),
        }
        native_restore = {
            "kind": "sqlite_file_restore",
            "command": f"cp {quote(str(sqlite_backup_path))} {quote(str(sqlite_db_path))}",
            "requires": ["stop memco writers first", "keep a pre-restore copy of the current db file"],
        }
        corruption_check = {
            "kind": "sqlite_integrity_check",
            "command": f"sqlite3 {quote(str(sqlite_db_path))} \"PRAGMA integrity_check;\"",
            "expected_output": "ok",
        }
    else:
        native_backup = {
            "kind": "postgres_dump",
            "command": f"pg_dump \"$MEMCO_POSTGRES_DATABASE_URL\" --format=custom --file {quote(str(postgres_dump_path))}",
            "output_path": str(postgres_dump_path),
        }
        native_restore = {
            "kind": "postgres_restore",
            "command": f"pg_restore --clean --if-exists --no-owner --dbname \"$MEMCO_POSTGRES_DATABASE_URL\" {quote(str(postgres_dump_path))}",
            "requires": ["target database selected through MEMCO_POSTGRES_DATABASE_URL", "operator has confirmed this is the intended restore target"],
        }
        corruption_check = {
            "kind": "postgres_dump_list_check",
            "command": f"pg_restore --list {quote(str(postgres_dump_path))}",
            "expected_output": "table-of-contents listing exits 0",
        }
    return {
        "artifact_type": "backup_restore_runbook",
        "storage_engine": engine,
        "root": str(settings.root),
        "native_backup": native_backup,
        "native_restore": native_restore,
        "corruption_check": corruption_check,
        "json_exports": {
            "audit_redacted": {
                "command": f"uv run memco backup export --mode audit --output {quote(str(audit_json_path))} --root {quote(str(settings.root))}",
                "verify": f"uv run memco backup verify {quote(str(audit_json_path))}",
                "restorable": False,
            },
            "full_encrypted": {
                "command": f"MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup export --mode full --encrypted --output {quote(str(encrypted_json_path))} --root {quote(str(settings.root))}",
                "verify": f"MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup verify {quote(str(encrypted_json_path))}",
                "restore_dry_run": f"MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup restore-dry-run {quote(str(encrypted_json_path))}",
                "restorable": True,
            },
        },
        "notes": [
            "Audit JSON exports are redacted and are not restore sources.",
            "Full encrypted JSON exports are verified with restore-dry-run before any native restore.",
            "Native restore commands are destructive; run them only after stopping Memco writers and confirming the target.",
        ],
    }


def _backup_encrypted_flag(path: Path) -> bool:
    try:
        return BackupService().is_encrypted_backup(path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@backup_app.command("runbook", help="Print engine-specific backup, restore, encryption, and corruption-check commands.")
def backup_runbook_command(
    storage_engine: str | None = typer.Option(None, help="Override storage engine for the runbook: sqlite|postgres."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    result = _backup_runbook(settings, storage_engine=storage_engine)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@backup_app.command("export", help="Write an audit or full backup export. Use --encrypted for passphrase-protected output.")
def backup_export_command(
    output: str | None = typer.Option(None, help="Output path. Defaults under var/backups."),
    mode: str = typer.Option("audit", help="Export mode: audit|full. Audit mode redacts raw source text."),
    encrypted: bool = typer.Option(False, "--encrypted", help="Encrypt the export with MEMCO_BACKUP_PASSPHRASE."),
    passphrase_env: str | None = typer.Option(None, help="Environment variable holding the backup passphrase."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    normalized_mode = mode.strip().lower()
    output_path = Path(output).expanduser().resolve() if output else _default_backup_output(
        settings,
        mode=normalized_mode,
        encrypted=encrypted,
    )
    passphrase = _backup_passphrase(encrypted_or_required=encrypted, passphrase_env=passphrase_env)
    service = BackupService()
    with get_connection(settings.db_path) as conn:
        try:
            result = service.export_backup(
                conn,
                output_path=output_path,
                storage_engine=settings.storage.engine,
                mode=normalized_mode,
                encrypted=encrypted,
                passphrase=passphrase,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@backup_app.command("verify", help="Verify a backup export and check migration compatibility.")
def backup_verify_command(
    backup_path: str = typer.Argument(..., help="Backup JSON or encrypted JSON path."),
    passphrase_env: str | None = typer.Option(None, help="Environment variable holding the backup passphrase."),
) -> None:
    path = Path(backup_path).expanduser().resolve()
    encrypted = _backup_encrypted_flag(path)
    passphrase = _backup_passphrase(encrypted_or_required=encrypted, passphrase_env=passphrase_env)
    try:
        result = BackupService().verify_backup(path, passphrase=passphrase)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(1)


@backup_app.command("restore-dry-run", help="Validate a backup for restore without writing to the runtime database.")
def backup_restore_dry_run_command(
    backup_path: str = typer.Argument(..., help="Backup JSON or encrypted JSON path."),
    passphrase_env: str | None = typer.Option(None, help="Environment variable holding the backup passphrase."),
) -> None:
    path = Path(backup_path).expanduser().resolve()
    encrypted = _backup_encrypted_flag(path)
    passphrase = _backup_passphrase(encrypted_or_required=encrypted, passphrase_env=passphrase_env)
    try:
        result = BackupService().restore_dry_run(path, passphrase=passphrase)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(1)


@app.command("fact-operations", help="List fact lifecycle operations. Often used before `fact-rollback`. Omit `--target-fact-id` with `--latest-target-fact` to target the newest matching fact in the current scope.")
def fact_operations_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    target_fact_id: int | None = typer.Option(None, help="Fact id filter."),
    latest_target_fact: bool = typer.Option(
        False,
        help="Use the newest matching fact in the current scope for `--target-fact-id`. Combine with `--person-slug` and/or `--domain` to avoid workspace-wide ambiguity.",
    ),
    domain: str | None = typer.Option(None, help="Optional domain filter for `--latest-target-fact`."),
    operation_type: str | None = typer.Option(None, help="Operation type filter."),
    limit: int = typer.Option(50, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_target_fact_id = _resolve_cli_id(
            explicit_id=target_fact_id,
            latest=latest_target_fact,
            id_label="target_fact_id",
            latest_label="--latest-target-fact",
            resolver=lambda: _latest_fact_id(
                conn,
                workspace_slug=workspace,
                person_id=resolved_person_id,
                domain=domain,
            ),
        ) if (target_fact_id is not None or latest_target_fact) else None
        result = repository.list_operations(
            conn,
            workspace_slug=workspace,
            person_id=resolved_person_id,
            target_fact_id=resolved_target_fact_id,
            operation_type=operation_type,
            limit=limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "fact-delete",
    help="Mark a fact deleted. Next step: `fact-restore`, `fact-operations`, or `retrieve`. Omit FACT_ID with `--latest-fact` to target the newest matching fact in the current scope.",
)
def fact_delete_command(
    fact_id: int | None = typer.Argument(None, help="Fact id. Omit with `--latest-fact`."),
    latest_fact: bool = typer.Option(
        False,
        help="Use the newest matching fact in the current scope. Combine with `--person-slug` and/or `--domain` to avoid workspace-wide ambiguity.",
    ),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter for `--latest-fact`."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter for `--latest-fact`."),
    status: str | None = typer.Option(None, help="Optional status filter for `--latest-fact`."),
    domain: str | None = typer.Option(None, help="Optional domain filter for `--latest-fact`."),
    reason: str = typer.Option("", help="Deletion reason."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_fact_id = _resolve_cli_id(
            explicit_id=fact_id,
            latest=latest_fact,
            id_label="fact_id",
            latest_label="--latest-fact",
            resolver=lambda: _latest_fact_id(
                conn,
                workspace_slug=workspace,
                person_id=resolved_person_id,
                status=status,
                domain=domain,
            ),
        )
        result = service.mark_deleted(conn, fact_id=resolved_fact_id, reason=reason)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "fact-restore",
    help="Restore a deleted fact. Next step: `retrieve`, `fact-list`, or `fact-operations`. Omit FACT_ID with `--latest-fact` to target the newest matching fact in the current scope.",
)
def fact_restore_command(
    fact_id: int | None = typer.Argument(None, help="Fact id. Omit with `--latest-fact`."),
    latest_fact: bool = typer.Option(
        False,
        help="Use the newest matching fact in the current scope. Combine with `--person-slug` and/or `--domain` to avoid workspace-wide ambiguity.",
    ),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter for `--latest-fact`."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter for `--latest-fact`."),
    status: str | None = typer.Option(None, help="Optional status filter for `--latest-fact`."),
    domain: str | None = typer.Option(None, help="Optional domain filter for `--latest-fact`."),
    reason: str = typer.Option("", help="Restore reason."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_fact_id = _resolve_cli_id(
            explicit_id=fact_id,
            latest=latest_fact,
            id_label="fact_id",
            latest_label="--latest-fact",
            resolver=lambda: _latest_fact_id(
                conn,
                workspace_slug=workspace,
                person_id=resolved_person_id,
                status=status,
                domain=domain,
            ),
        )
        result = service.restore(conn, fact_id=resolved_fact_id, reason=reason)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "fact-rollback",
    help="Roll back a fact lifecycle operation. Next step: `fact-list`, `fact-operations`, or `retrieve` to confirm the truth store.",
)
def fact_rollback_command(
    operation_id: int | None = typer.Argument(None, help="Operation id. Omit with `--latest-operation`."),
    latest_operation: bool = typer.Option(
        False,
        help="Use the newest matching operation in the current scope. Combine with `--person-slug`, `--target-fact-id`, and/or `--operation-type` to avoid workspace-wide ambiguity.",
    ),
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Optional person filter for `--latest-operation`."),
    person_slug: str | None = typer.Option(None, help="Optional person slug filter for `--latest-operation`."),
    target_fact_id: int | None = typer.Option(None, help="Optional target fact filter for `--latest-operation`."),
    operation_type: str | None = typer.Option(None, help="Optional operation type filter for `--latest-operation`."),
    reason: str = typer.Option("", help="Rollback reason."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        resolved_operation_id = _resolve_cli_id(
            explicit_id=operation_id,
            latest=latest_operation,
            id_label="operation_id",
            latest_label="--latest-operation",
            resolver=lambda: _latest_operation_id(
                conn,
                workspace_slug=workspace,
                person_id=resolved_person_id,
                target_fact_id=target_fact_id,
                operation_type=operation_type,
            ),
        )
        result = service.rollback(conn, operation_id=resolved_operation_id, reason=reason)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "retrieval-log-list",
    help="List redacted retrieval logs. Often used after `retrieve` or `chat` to inspect operator activity.",
)
def retrieval_log_list_command(
    workspace: str = typer.Option("default", help="Workspace slug."),
    person_id: int | None = typer.Option(None, help="Person id filter."),
    person_slug: str | None = typer.Option(None, help="Person slug filter."),
    route_name: str | None = typer.Option(None, help="Route filter."),
    limit: int = typer.Option(50, help="Result limit."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    repository = RetrievalLogRepository()
    with get_connection(settings.db_path) as conn:
        resolved_person_id = _resolve_person_option(
            conn=conn,
            workspace_slug=workspace,
            person_id=person_id,
            person_slug=person_slug,
            option_name="person",
        )
        result = repository.list_logs(
            conn,
            workspace_slug=workspace,
            person_id=resolved_person_id,
            route_name=route_name,
            limit=limit,
        )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("eval-run", help="Run the acceptance-style eval artifact. Often used before or after `release-check`.")
def eval_run_command(
    root: str | None = typer.Option(None, help="Project root."),
    seed_fixture: bool = typer.Option(True, help="Seed fixture data before running eval."),
) -> None:
    settings = _eval_settings(root)
    service = EvalService()
    if seed_fixture:
        service.seed_fixture_data(settings.root)
    result = service.run(settings.root)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def _resolve_personal_goldens_dir(goldens: str) -> Path:
    requested = Path(goldens).expanduser()
    candidates = [requested] if requested.is_absolute() else [Path.cwd() / requested]
    if not requested.is_absolute():
        candidates.append(Path.cwd() / "eval" / "personal_memory_goldens" / requested.name)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved.parent
        if resolved.is_dir():
            return resolved
    return candidates[0].resolve()


def _run_personal_memory_eval_command(*, goldens: str, output: str | None, root: str | None) -> None:
    goldens_dir = _resolve_personal_goldens_dir(goldens)
    service = EvalService()
    if root:
        settings = _eval_settings(root)
        result = service.run_personal_memory(project_root=settings.root, goldens_dir=goldens_dir)
    else:
        with TemporaryDirectory(prefix="memco-personal-memory-eval-") as tmpdir:
            settings = _eval_settings(tmpdir)
            result = service.run_personal_memory(project_root=settings.root, goldens_dir=goldens_dir)
    try:
        context_root = _project_root(None)
    except typer.BadParameter:
        context_root = settings.root
    attach_artifact_context(result, project_root=context_root)
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(1)


@eval_app.command("personal-memory", help="Run the personal-memory golden eval gate.")
def eval_personal_memory_command(
    goldens: str = typer.Option("eval/personal_memory_goldens", help="Directory or JSONL file containing personal-memory goldens."),
    output: str | None = typer.Option(None, help="Optional JSON artifact output path."),
    root: str | None = typer.Option(None, help="Optional isolated fixture runtime root. Defaults to a temporary root."),
) -> None:
    _run_personal_memory_eval_command(goldens=goldens, output=output, root=root)


@app.command("personal-memory-eval", help="Compatibility alias for `eval personal-memory`.")
def personal_memory_eval_command(
    goldens: str = typer.Option("eval/personal_memory_goldens", help="Directory or JSONL file containing personal-memory goldens."),
    output: str | None = typer.Option(None, help="Optional JSON artifact output path."),
    root: str | None = typer.Option(None, help="Optional isolated fixture runtime root. Defaults to a temporary root."),
) -> None:
    _run_personal_memory_eval_command(goldens=goldens, output=output, root=root)


@app.command(
    "release-check",
    help="Run the release gate. Default mode is the quick repo-local gate; adding --postgres-database-url upgrades it to the canonical Postgres gate. Use `strict-release-check` for the benchmark-backed quality claim.",
)
def release_check_command(
    root: str | None = typer.Option(None, help="Temporary runtime root for the eval fixture run."),
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    postgres_database_url: str | None = typer.Option(
        None,
        help="Postgres maintenance URL for the canonical Postgres gate. When set, acceptance runs on Postgres and the API bootstrap smoke is required.",
    ),
    postgres_port: int | None = typer.Option(None, help="Optional port for the temporary Postgres smoke API run."),
    fixture_ok: bool = typer.Option(
        False,
        "--fixture-ok",
        help="Run an archive-safe fixture gate. The artifact is explicitly fixture_only=true and release_eligible=false.",
    ),
    include_realistic_eval: bool = typer.Option(
        False,
        "--include-realistic-eval",
        help="Also run the realistic personal-memory JSONL eval gate from eval/personal_memory_goldens.",
    ),
    output: str | None = typer.Option(None, help="Optional file path to save the release artifact JSON."),
) -> None:
    eval_root = Path(root).expanduser().resolve() if root else None
    resolved_project_root = _project_root(project_root)
    postgres_root = None
    if eval_root is not None and postgres_database_url:
        postgres_root = eval_root.parent / f"{eval_root.name}-postgres-smoke"
    result = run_release_check(
        project_root=resolved_project_root,
        eval_root=eval_root,
        include_eval=True,
        include_realistic_eval=include_realistic_eval,
        fixture_ok=fixture_ok,
        postgres_database_url=postgres_database_url,
        postgres_root=postgres_root,
        postgres_port=postgres_port,
    )
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command(
    "strict-release-check",
    help="Run the benchmark-backed strict quality gate. This path is required for the full quality claim and always includes the canonical Postgres gate plus benchmark thresholds.",
)
def strict_release_check_command(
    root: str | None = typer.Option(None, help="Temporary runtime root for the eval fixture run."),
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    postgres_database_url: str | None = typer.Option(
        None,
        help="Required Postgres maintenance URL for the canonical Postgres + benchmark quality gate.",
    ),
    postgres_port: int | None = typer.Option(None, help="Optional port for the temporary Postgres smoke API run."),
    output: str | None = typer.Option(None, help="Optional file path to save the strict release artifact JSON."),
) -> None:
    if not postgres_database_url:
        raise typer.BadParameter("--postgres-database-url is required for strict-release-check")
    eval_root = Path(root).expanduser().resolve() if root else None
    resolved_project_root = _project_root(project_root)
    postgres_root = None
    if eval_root is not None:
        postgres_root = eval_root.parent / f"{eval_root.name}-postgres-smoke"
    result = run_strict_release_check(
        project_root=resolved_project_root,
        eval_root=eval_root,
        postgres_database_url=postgres_database_url,
        postgres_root=postgres_root,
        postgres_port=postgres_port,
    )
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command(
    "release-readiness-check",
    help="Run the release-grade gate. This requires canonical Postgres, strict benchmark thresholds, and live operator smoke.",
)
def release_readiness_check_command(
    root: str | None = typer.Option(None, help="Temporary runtime root for the eval fixture run."),
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    postgres_database_url: str | None = typer.Option(
        None,
        help="Required Postgres maintenance URL for the release-grade gate.",
    ),
    postgres_port: int | None = typer.Option(None, help="Optional port for the temporary Postgres smoke API run."),
    require_live_provider: bool = typer.Option(
        False,
        "--require-live-provider",
        help="Document and enforce the release-grade intent: live smoke must be requested with MEMCO_RUN_LIVE_SMOKE=1.",
    ),
    require_postgres: bool = typer.Option(
        False,
        "--require-postgres",
        help="Document and enforce the release-grade intent: --postgres-database-url is required.",
    ),
    output: str | None = typer.Option(None, help="Optional file path to save the release-grade artifact JSON."),
) -> None:
    if not postgres_database_url:
        raise typer.BadParameter("--postgres-database-url is required for release-readiness-check")
    if require_live_provider and os.environ.get("MEMCO_RUN_LIVE_SMOKE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise typer.BadParameter("--require-live-provider requires MEMCO_RUN_LIVE_SMOKE=1")
    if require_postgres and not postgres_database_url:
        raise typer.BadParameter("--require-postgres requires --postgres-database-url")
    eval_root = Path(root).expanduser().resolve() if root else None
    resolved_project_root = _project_root(project_root)
    postgres_root = None
    if eval_root is not None:
        postgres_root = eval_root.parent / f"{eval_root.name}-postgres-smoke"
    result = run_release_readiness_check(
        project_root=resolved_project_root,
        eval_root=eval_root,
        postgres_database_url=postgres_database_url,
        postgres_root=postgres_root,
        postgres_port=postgres_port,
    )
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command(
    "operator-preflight",
    help="Check the operator-configured runtime before release-grade validation.",
)
def operator_preflight_command(
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    postgres_database_url: str | None = typer.Option(
        None,
        help="Optional Postgres URL to check instead of the configured runtime database URL.",
    ),
    output: str | None = typer.Option(None, help="Optional file path to save the preflight artifact JSON."),
) -> None:
    resolved_project_root = _project_root(project_root)
    result = run_operator_preflight(
        project_root=resolved_project_root,
        postgres_database_url=postgres_database_url,
    )
    _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command(
    "local-artifacts-refresh",
    help="Refresh local operator artifacts under var/reports, including release-check snapshots, repo-local status JSON, and change-group JSON.",
)
def local_artifacts_refresh_command(
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
    postgres_database_url: str | None = typer.Option(
        None,
        help="Optional Postgres maintenance URL. If set, also refresh the Postgres-smoke release-check artifact.",
    ),
    output: str | None = typer.Option(None, help="Optional file path to save the command summary JSON."),
) -> None:
    resolved_project_root = _project_root(project_root)
    try:
        result = refresh_local_artifacts(
            project_root=resolved_project_root,
            postgres_database_url=postgres_database_url,
        )
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _emit_json_artifact(result, output=output)


@app.command(
    "postgres-smoke",
    help="Run a no-Docker Postgres smoke against MEMCO_DATABASE_URL using a temporary database.",
)
def postgres_smoke_command(
    database_url: str | None = typer.Option(None, help="Postgres maintenance database URL. Defaults to MEMCO_DATABASE_URL."),
    root: str | None = typer.Option(None, help="Temporary runtime root."),
    port: int | None = typer.Option(None, help="Port for temporary API run."),
    project_root: str | None = typer.Option(None, help="Repo root. Defaults to the nearest Memco checkout above the current directory."),
) -> None:
    selected_database_url = database_url or load_settings(root).storage.database_url or os.environ.get("MEMCO_DATABASE_URL", "")
    if not selected_database_url:
        raise typer.BadParameter("database_url or MEMCO_DATABASE_URL is required")
    runtime_root = Path(root).expanduser().resolve() if root else Path("/tmp/memco-postgres-smoke").resolve()
    resolved_project_root = _project_root(project_root)
    result = run_postgres_smoke(
        database_url=selected_database_url,
        root=runtime_root,
        port=port,
        project_root=resolved_project_root,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(
    "postgres-bootstrap",
    help="Create a persistent Postgres database from a maintenance URL and print the next runtime env values.",
)
def postgres_bootstrap_command(
    db_name: str = typer.Argument(..., help="Database name to create."),
    database_url: str | None = typer.Option(None, help="Maintenance Postgres URL. Defaults to MEMCO_DATABASE_URL."),
    root: str | None = typer.Option(None, help="Runtime root to suggest in the output."),
) -> None:
    maintenance_database_url = database_url or os.environ.get("MEMCO_DATABASE_URL", "")
    if not maintenance_database_url:
        raise typer.BadParameter("database_url or MEMCO_DATABASE_URL is required")
    runtime_root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()
    target_url = ensure_postgres_database(
        maintenance_database_url=maintenance_database_url,
        db_name=db_name,
    )
    typer.echo(
        json.dumps(
            {
                "db_name": db_name,
                "database_url": target_url,
                "root": str(runtime_root),
                "next": [
                    f"export MEMCO_STORAGE_ENGINE=postgres",
                    f"export MEMCO_DATABASE_URL='{target_url}'",
                    f"uv run memco init-db --root '{runtime_root}'",
                    "uv run memco-api",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

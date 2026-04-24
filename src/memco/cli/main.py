from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from memco.api.deps import build_internal_actor
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
from memco.services.export_service import ExportService
from memco.services.backup_service import BackupService
from memco.services.chat_runtime import build_chat_services
from memco.services.review_service import ReviewService
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


def _backup_passphrase(*, encrypted_or_required: bool, passphrase_env: str | None) -> str | None:
    env_name = passphrase_env or "MEMCO_BACKUP_PASSPHRASE"
    value = os.environ.get(env_name)
    if encrypted_or_required and not value:
        raise typer.BadParameter(f"{env_name} must be set for encrypted backup operations.")
    return value


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


@app.command(
    "import",
    help="Import a source file into the workspace. For conversations, next step: `conversation-import SOURCE_ID`.",
)
def import_command(
    path: str,
    source_type: str = typer.Option("note", help="Source type."),
    workspace: str = typer.Option("default", help="Workspace slug."),
    root: str | None = typer.Option(None, help="Project root."),
) -> None:
    settings = _settings(root)
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug=workspace,
            path=Path(path),
            source_type=source_type,
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


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


def _backup_encrypted_flag(path: Path) -> bool:
    try:
        return BackupService().is_encrypted_backup(path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


@eval_app.command("personal-memory", help="Run the personal-memory golden eval gate.")
def eval_personal_memory_command(
    goldens: str = typer.Option("eval/personal_memory_goldens", help="Directory containing personal-memory JSONL goldens."),
    output: str | None = typer.Option(None, help="Optional JSON artifact output path."),
    root: str | None = typer.Option(None, help="Optional isolated fixture runtime root. Defaults to a temporary root."),
) -> None:
    goldens_dir = Path(goldens).expanduser().resolve()
    service = EvalService()
    if root:
        settings = _eval_settings(root)
        result = service.run_personal_memory(project_root=settings.root, goldens_dir=goldens_dir)
        _emit_json_artifact(result, output=output)
    else:
        with TemporaryDirectory(prefix="memco-personal-memory-eval-") as tmpdir:
            settings = _eval_settings(tmpdir)
            result = service.run_personal_memory(project_root=settings.root, goldens_dir=goldens_dir)
            _emit_json_artifact(result, output=output)
    if not result["ok"]:
        raise typer.Exit(1)


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
    output: str | None = typer.Option(None, help="Optional file path to save the release-grade artifact JSON."),
) -> None:
    if not postgres_database_url:
        raise typer.BadParameter("--postgres-database-url is required for release-readiness-check")
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

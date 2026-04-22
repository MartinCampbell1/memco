from __future__ import annotations

from fastapi import APIRouter, Header

from memco.api.deps import get_settings, require_api_auth, resolve_actor_context
from memco.db import get_connection
from memco.models.memory_fact import PersonAliasUpsertRequest, PersonMergeRequest, PersonUpsertRequest
from memco.models.person import PersonListRequest
from memco.repositories.fact_repository import FactRepository

router = APIRouter()


@router.post("/v1/persons/list")
def list_persons(
    request: PersonListRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/persons/list",
        allowed_actor_types={"owner", "admin", "eval", "system"},
        require_actor=True,
    )
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        items = repository.list_persons(
            conn,
            workspace_slug=request.workspace,
            status=request.status,
            limit=request.limit,
        )
    return {"items": items}


@router.post("/v1/persons/upsert")
def upsert_person(
    request: PersonUpsertRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/persons/upsert",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        result = repository.upsert_person(
            conn,
            workspace_slug=request.workspace,
            display_name=request.display_name,
            slug=request.slug,
            person_type=request.person_type,
            aliases=request.aliases,
        )
    return result


@router.post("/v1/persons/aliases/upsert")
def upsert_person_alias(
    request: PersonAliasUpsertRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/persons/aliases/upsert",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        person_id = request.person_id
        if person_id is None:
            person_id = repository.resolve_person_id(
                conn,
                workspace_slug=request.workspace,
                person_slug=request.person_slug,
            )
        result = repository.upsert_person_alias(
            conn,
            workspace_slug=request.workspace,
            person_id=int(person_id),
            alias=request.alias,
            alias_type=request.alias_type,
        )
    return result


@router.post("/v1/persons/merge")
def merge_persons(
    request: PersonMergeRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/persons/merge",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        from_person_id = request.from_person_id
        if from_person_id is None:
            from_person_id = repository.resolve_person_id(
                conn,
                workspace_slug=request.workspace,
                person_slug=request.from_person_slug,
            )
        to_person_id = request.to_person_id
        if to_person_id is None:
            to_person_id = repository.resolve_person_id(
                conn,
                workspace_slug=request.workspace,
                person_slug=request.to_person_slug,
            )
        result = repository.merge_persons(
            conn,
            workspace_slug=request.workspace,
            from_person_id=int(from_person_id),
            to_person_id=int(to_person_id),
            reason=request.reason,
        )
    return result

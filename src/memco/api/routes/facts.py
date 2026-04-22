from __future__ import annotations

from fastapi import APIRouter, Header

from memco.api.deps import get_settings, require_api_auth
from memco.db import get_connection
from memco.models.fact import FactListRequest, FactOperationListRequest, FactRollbackRequest, FactStatusUpdateRequest
from memco.repositories.fact_repository import FactRepository
from memco.services.consolidation_service import ConsolidationService

router = APIRouter()


@router.post("/v1/facts/list")
def list_facts(
    request: FactListRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        items = repository.list_facts(
            conn,
            workspace_slug=request.workspace,
            person_id=request.person_id,
            status=request.status,
            domain=request.domain,
            limit=request.limit,
        )
    return {"items": items}


@router.post("/v1/facts/operations")
def list_fact_operations(
    request: FactOperationListRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    repository = FactRepository()
    with get_connection(settings.db_path) as conn:
        items = repository.list_operations(
            conn,
            workspace_slug=request.workspace,
            person_id=request.person_id,
            target_fact_id=request.target_fact_id,
            operation_type=request.operation_type,
            limit=request.limit,
        )
    return {"items": items}


@router.post("/v1/facts/delete")
def delete_fact(
    request: FactStatusUpdateRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        result = service.mark_deleted(conn, fact_id=request.fact_id, reason=request.reason)
    return result


@router.post("/v1/facts/restore")
def restore_fact(
    request: FactStatusUpdateRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        result = service.restore(conn, fact_id=request.fact_id, reason=request.reason)
    return result


@router.post("/v1/facts/rollback")
def rollback_fact_operation(
    request: FactRollbackRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        result = service.rollback(conn, operation_id=request.operation_id, reason=request.reason)
    return result

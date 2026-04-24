from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from memco.api.deps import get_settings, require_api_auth, resolve_actor_context
from memco.db import get_connection
from memco.models.candidate import (
    CandidateExtractRequest,
    CandidateListRequest,
    CandidatePublishRequest,
    CandidateRejectRequest,
)
from memco.repositories.fact_repository import FactRepository
from memco.services.candidate_service import CandidateService
from memco.services.extraction_service import ExtractionService
from memco.services.publish_service import PublishService

router = APIRouter()


@router.post("/v1/candidates/extract")
def extract_candidates(
    request: CandidateExtractRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/candidates/extract",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    service = CandidateService(extraction_service=ExtractionService.from_settings(settings))
    with get_connection(settings.db_path) as conn:
        fact_repository = FactRepository()
        attribution_policy = request.attribution_policy or settings.ingest.attribution_policy
        owner_person_id = request.owner_person_id
        owner_display_name = request.owner_display_name
        owner_person_slug = (request.owner_person_slug or settings.owner.person_slug) if attribution_policy == "owner_first_person_fallback" else ""
        if owner_person_id is None and owner_person_slug:
            try:
                owner_person_id = fact_repository.resolve_person_id(
                    conn,
                    workspace_slug=request.workspace,
                    person_slug=owner_person_slug,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if owner_person_id is not None and not owner_display_name:
            owner = fact_repository.get_person(
                conn,
                workspace_slug=request.workspace,
                person_id=owner_person_id,
            )
            owner_display_name = str(owner.get("display_name") or "") if owner else ""
        result = service.extract_from_conversation(
            conn,
            workspace_slug=request.workspace,
            conversation_id=request.conversation_id,
            include_style=request.include_style,
            include_psychometrics=request.include_psychometrics,
            owner_person_id=owner_person_id,
            owner_display_name=owner_display_name,
            attribution_policy=attribution_policy,
        )
    return {"items": result}


@router.post("/v1/candidates/list")
def list_candidates(
    request: CandidateListRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/candidates/list",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    service = CandidateService()
    with get_connection(settings.db_path) as conn:
        result = service.list_candidates(
            conn,
            workspace_slug=request.workspace,
            person_id=request.person_id,
            candidate_status=request.candidate_status,
            domain=request.domain,
            limit=request.limit,
        )
    return {"items": result}


@router.post("/v1/candidates/publish")
def publish_candidate(
    request: CandidatePublishRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/candidates/publish",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    service = PublishService()
    with get_connection(settings.db_path) as conn:
        try:
            result = service.publish_candidate(
                conn,
                workspace_slug=request.workspace,
                candidate_id=request.candidate_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
    return result


@router.post("/v1/candidates/reject")
def reject_candidate(
    request: CandidateRejectRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/candidates/reject",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    service = PublishService()
    with get_connection(settings.db_path) as conn:
        try:
            result = service.reject_candidate(
                conn,
                candidate_id=request.candidate_id,
                reason=request.reason,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
    return result

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from memco.api.deps import get_settings, require_api_auth
from memco.db import get_connection
from memco.models.review import ReviewListRequest, ReviewResolveRequest
from memco.services.review_service import ReviewService

router = APIRouter()


@router.post("/v1/review/list")
def list_review_items(
    request: ReviewListRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ReviewService()
    with get_connection(settings.db_path) as conn:
        items = service.list_items(
            conn,
            workspace_slug=request.workspace,
            status=request.status,
            person_id=request.person_id,
            limit=request.limit,
        )
    return {"items": items}


@router.post("/v1/review/resolve")
def resolve_review_item(
    request: ReviewResolveRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ReviewService()
    with get_connection(settings.db_path) as conn:
        try:
            result = service.resolve_with_person(
                conn,
                queue_id=request.queue_id,
                decision=request.decision,
                reason=request.reason,
                candidate_person_id=request.candidate_person_id,
                candidate_target_person_id=request.candidate_target_person_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    return result

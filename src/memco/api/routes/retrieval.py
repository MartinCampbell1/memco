from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from memco.api.deps import get_settings, require_api_auth
from memco.db import get_connection
from memco.models.retrieval import RetrievalRequest
from memco.services.retrieval_service import RetrievalService

router = APIRouter()


@router.post("/v1/retrieve")
def retrieve_memory(
    request: RetrievalRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    if request.actor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Actor context is required for /v1/retrieve.",
        )
    service = RetrievalService()
    with get_connection(settings.db_path) as conn:
        result = service.retrieve(conn, request, settings=settings, route_name="retrieve")
    return result.model_dump(mode="json")

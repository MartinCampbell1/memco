from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from memco.api.deps import get_settings, require_api_auth
from memco.db import get_connection
from memco.models.retrieval import RetrievalRequest
from memco.services.refusal_service import RefusalService
from memco.services.retrieval_service import RetrievalService

router = APIRouter()


@router.post("/v1/chat")
def chat_with_memory(
    request: RetrievalRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    if request.actor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Actor context is required for /v1/chat.",
        )
    retrieval_service = RetrievalService()
    refusal_service = RefusalService()
    with get_connection(settings.db_path) as conn:
        retrieval_result = retrieval_service.retrieve(conn, request, settings=settings, route_name="chat")
    answer = refusal_service.build_answer(query=request.query, retrieval_result=retrieval_result)
    return {
        "query": request.query,
        "retrieval": retrieval_result.model_dump(mode="json"),
        **answer,
    }

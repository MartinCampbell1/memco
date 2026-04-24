from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from memco.api.deps import get_settings, require_api_auth, resolve_actor_context
from memco.db import get_connection
from memco.models.retrieval import RetrievalRequest
from memco.services.chat_runtime import build_chat_services

router = APIRouter()


@router.post("/v1/chat")
def chat_with_memory(
    request: RetrievalRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    actor = resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/chat",
        allowed_actor_types={"owner", "system"},
        require_actor=True,
    )
    retrieval_service, answer_service = build_chat_services(settings)
    with get_connection(settings.db_path) as conn:
        retrieval_result = retrieval_service.retrieve(
            conn,
            request.model_copy(update={"actor": actor}),
            settings=settings,
            route_name="chat",
        )
    answer = answer_service.build_answer(
        query=request.query,
        retrieval_result=retrieval_result,
        detail_policy=request.detail_policy,
    )
    return {
        "query": request.query,
        "retrieval": retrieval_service.present_result(retrieval_result, detail_policy=request.detail_policy),
        **answer,
    }

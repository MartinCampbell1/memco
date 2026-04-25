from __future__ import annotations

from fastapi import APIRouter, Header

from memco.api.deps import get_settings, require_api_auth, resolve_actor_context
from memco.db import get_connection
from memco.models.agent import AgentMemoryContextRequest
from memco.services.agent_context_service import AgentContextService
from memco.services.chat_runtime import build_chat_services

router = APIRouter()


@router.post("/v1/agent/memory-context")
def agent_memory_context(
    request: AgentMemoryContextRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    actor = resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/agent/memory-context",
        allowed_actor_types={"owner", "system"},
        require_actor=True,
    )
    retrieval_service, _answer_service = build_chat_services(settings)
    service = AgentContextService(retrieval_service=retrieval_service)
    with get_connection(settings.db_path) as conn:
        return service.memory_context(conn, request, settings=settings, actor=actor)

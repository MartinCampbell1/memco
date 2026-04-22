from __future__ import annotations

from fastapi import APIRouter, Header

from memco.api.deps import get_settings, require_api_auth, resolve_actor_context
from memco.db import get_connection
from memco.models.export import PersonaExportRequest
from memco.services.export_service import ExportService

router = APIRouter()


@router.post("/v1/persona/export")
def export_persona(
    request: PersonaExportRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    actor = resolve_actor_context(
        settings,
        request.actor,
        route_label="/v1/persona/export",
        allowed_actor_types={"owner", "admin", "system"},
        require_actor=True,
    )
    service = ExportService()
    with get_connection(settings.db_path) as conn:
        result = service.export_persona(
            settings,
            conn,
            workspace_slug=request.workspace,
            person_id=request.person_id,
            person_slug=request.person_slug,
            domain=request.domain,
            detail_policy=request.detail_policy,
            actor=actor,
        )
    return result

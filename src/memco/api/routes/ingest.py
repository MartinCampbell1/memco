from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Header

from memco.api.deps import get_settings, require_api_auth
from memco.db import get_connection
from memco.models.conversation import (
    ConversationImportRequest,
    ConversationSpeakerListRequest,
    ConversationSpeakerResolveRequest,
)
from memco.models.source import ImportSourceRequest, ImportTextRequest, IngestPipelineRequest
from memco.services.pipeline_service import IngestPipelineService
from memco.services.candidate_service import CandidateService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService

router = APIRouter()


@router.post("/v1/ingest")
def ingest_source(
    request: ImportSourceRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug=request.workspace,
            path=Path(request.path),
            source_type=request.source_type,
        )
    return result.model_dump(mode="json")


@router.post("/v1/ingest/text")
def ingest_text(
    request: ImportTextRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_text(
            settings,
            conn,
            workspace_slug=request.workspace,
            text=request.text,
            title=request.title,
            source_type=request.source_type,
        )
    return result.model_dump(mode="json")


@router.post("/v1/ingest/pipeline")
def ingest_pipeline(
    request: IngestPipelineRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = IngestPipelineService()
    with get_connection(settings.db_path) as conn:
        if request.path:
            result = service.ingest_path(
                settings,
                conn,
                workspace_slug=request.workspace,
                path=Path(request.path),
                source_type=request.source_type,
                person_display_name=request.person_display_name,
                person_slug=request.person_slug,
                aliases=request.aliases,
                conversation_uid=request.conversation_uid,
                title=request.title,
                include_style=request.include_style,
                include_psychometrics=request.include_psychometrics,
            )
        else:
            result = service.ingest_text(
                settings,
                conn,
                workspace_slug=request.workspace,
                text=request.text or "",
                source_type=request.source_type,
                title=request.title,
                person_display_name=request.person_display_name,
                person_slug=request.person_slug,
                aliases=request.aliases,
                conversation_uid=request.conversation_uid,
                include_style=request.include_style,
                include_psychometrics=request.include_psychometrics,
            )
    return result


@router.post("/v1/ingest/conversation")
def ingest_conversation(
    request: ConversationImportRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ConversationIngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_conversation(
            settings,
            conn,
            workspace_slug=request.workspace,
            source_id=request.source_id,
            conversation_uid=request.conversation_uid,
            title=request.title,
        )
    return result.model_dump(mode="json")


@router.post("/v1/conversations/speakers")
def list_conversation_speakers(
    request: ConversationSpeakerListRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    service = ConversationIngestService()
    with get_connection(settings.db_path) as conn:
        items = service.list_speakers(
            conn,
            conversation_id=request.conversation_id,
        )
    return {"items": items}


@router.post("/v1/conversations/speakers/resolve")
def resolve_conversation_speaker(
    request: ConversationSpeakerResolveRequest,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
):
    settings = get_settings()
    require_api_auth(settings, authorization=authorization, x_memco_token=x_memco_token)
    conversation_service = ConversationIngestService()
    candidate_service = CandidateService(extraction_service=ExtractionService.from_settings(settings))
    with get_connection(settings.db_path) as conn:
        mapping = conversation_service.resolve_speaker(
            conn,
            workspace_slug=request.workspace,
            conversation_id=request.conversation_id,
            speaker_key=request.speaker_key,
            person_id=request.person_id,
            person_slug=request.person_slug,
            create_person_display_name=request.create_person_display_name,
            create_person_slug=request.create_person_slug,
        )
        candidates = candidate_service.reextract_for_speaker_resolution(
            conn,
            workspace_slug=request.workspace,
            conversation_id=request.conversation_id,
        )
    return {"mapping": mapping, "candidates": candidates}

from __future__ import annotations

from pathlib import Path

from memco.repositories.fact_repository import FactRepository
from memco.services.candidate_service import CandidateService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.services.publish_service import PublishService
from memco.services.review_service import ReviewService


class IngestPipelineService:
    def __init__(
        self,
        *,
        fact_repository: FactRepository | None = None,
        ingest_service: IngestService | None = None,
        conversation_service: ConversationIngestService | None = None,
        candidate_service: CandidateService | None = None,
        publish_service: PublishService | None = None,
        review_service: ReviewService | None = None,
    ) -> None:
        self.fact_repository = fact_repository or FactRepository()
        self.ingest_service = ingest_service or IngestService()
        self.conversation_service = conversation_service or ConversationIngestService()
        self.candidate_service = candidate_service
        self.publish_service = publish_service or PublishService()
        self.review_service = review_service or ReviewService()

    def _candidate_service(self, settings):
        if self.candidate_service is not None:
            return self.candidate_service
        return CandidateService(extraction_service=ExtractionService.from_settings(settings))

    def _run_pipeline(
        self,
        settings,
        conn,
        *,
        workspace_slug: str,
        imported,
        person_display_name: str | None,
        person_slug: str | None,
        aliases: list[str],
        conversation_uid: str,
        title: str,
        include_style: bool,
        include_psychometrics: bool,
    ) -> dict:
        person_result = None
        if person_display_name:
            person_result = self.fact_repository.upsert_person(
                conn,
                workspace_slug=workspace_slug,
                display_name=person_display_name,
                slug=person_slug,
                person_type="human",
                aliases=aliases,
            )

        conversation = self.conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug=workspace_slug,
            source_id=imported.source_id,
            conversation_uid=conversation_uid,
            title=title,
        )
        candidates = self._candidate_service(settings).extract_from_conversation(
            conn,
            workspace_slug=workspace_slug,
            conversation_id=conversation.conversation_id,
            include_style=include_style,
            include_psychometrics=include_psychometrics,
        )

        published: list[dict] = []
        publish_errors: list[dict] = []
        candidate_ids = {int(item["id"]) for item in candidates}
        for candidate in candidates:
            if candidate["candidate_status"] != "validated_candidate":
                continue
            try:
                published.append(
                    self.publish_service.publish_candidate(
                        conn,
                        workspace_slug=workspace_slug,
                        candidate_id=int(candidate["id"]),
                    )
                )
            except ValueError as exc:
                publish_errors.append({"candidate_id": int(candidate["id"]), "error": str(exc)})

        pending_review_items = self.review_service.review_repository.list_items_for_candidates(
            conn,
            workspace_slug=workspace_slug,
            candidate_ids=sorted(candidate_ids),
            status="pending",
        )

        return {
            "person": person_result,
            "import": imported.model_dump(mode="json"),
            "conversation": conversation.model_dump(mode="json"),
            "extracted_total": len(candidates),
            "validated_candidate_ids": [
                int(item["id"]) for item in candidates if item["candidate_status"] == "validated_candidate"
            ],
            "needs_review_candidate_ids": [
                int(item["id"]) for item in candidates if item["candidate_status"] == "needs_review"
            ],
            "published": published,
            "publish_errors": publish_errors,
            "pending_review_items": pending_review_items,
        }

    def ingest_path(
        self,
        settings,
        conn,
        *,
        workspace_slug: str,
        path: Path,
        source_type: str = "json",
        person_display_name: str | None = None,
        person_slug: str | None = None,
        aliases: list[str] | None = None,
        conversation_uid: str = "main",
        title: str = "",
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> dict:
        imported = self.ingest_service.import_file(
            settings,
            conn,
            workspace_slug=workspace_slug,
            path=path,
            source_type=source_type,
        )
        return self._run_pipeline(
            settings,
            conn,
            workspace_slug=workspace_slug,
            imported=imported,
            person_display_name=person_display_name,
            person_slug=person_slug,
            aliases=aliases or [],
            conversation_uid=conversation_uid,
            title=title,
            include_style=include_style,
            include_psychometrics=include_psychometrics,
        )

    def ingest_text(
        self,
        settings,
        conn,
        *,
        workspace_slug: str,
        text: str,
        source_type: str = "note",
        title: str = "",
        person_display_name: str | None = None,
        person_slug: str | None = None,
        aliases: list[str] | None = None,
        conversation_uid: str = "main",
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> dict:
        imported = self.ingest_service.import_text(
            settings,
            conn,
            workspace_slug=workspace_slug,
            text=text,
            title=title,
            source_type=source_type,
        )
        return self._run_pipeline(
            settings,
            conn,
            workspace_slug=workspace_slug,
            imported=imported,
            person_display_name=person_display_name,
            person_slug=person_slug,
            aliases=aliases or [],
            conversation_uid=conversation_uid,
            title=title,
            include_style=include_style,
            include_psychometrics=include_psychometrics,
        )

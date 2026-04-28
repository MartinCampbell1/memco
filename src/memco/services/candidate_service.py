from __future__ import annotations

from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.review_repository import ReviewRepository
from memco.services.extraction_service import ExtractionService


class CandidateService:
    def __init__(
        self,
        extraction_service: ExtractionService | None = None,
        candidate_repository: CandidateRepository | None = None,
        review_repository: ReviewRepository | None = None,
    ) -> None:
        self.extraction_service = extraction_service
        self.candidate_repository = candidate_repository or CandidateRepository()
        self.review_repository = review_repository or ReviewRepository()

    def _require_extraction_service(self) -> ExtractionService:
        if self.extraction_service is None:
            raise ValueError("CandidateService requires an explicit ExtractionService for extraction operations.")
        return self.extraction_service

    def extract_from_conversation(
        self,
        conn,
        *,
        workspace_slug: str,
        conversation_id: int,
        include_style: bool = False,
        include_psychometrics: bool = False,
        owner_person_id: int | None = None,
        owner_display_name: str = "",
        attribution_policy: str = "strict_speaker_only",
        max_chunks: int | None = None,
    ) -> list[dict]:
        extracted = self._require_extraction_service().extract_candidates_from_conversation(
            conn,
            conversation_id=conversation_id,
            include_style=include_style,
            include_psychometrics=include_psychometrics,
            owner_person_id=owner_person_id,
            owner_display_name=owner_display_name,
            attribution_policy=attribution_policy,
            max_chunks=max_chunks,
        )
        persisted: list[dict] = []
        for item in extracted:
            reason = item.get("reason", "")
            needs_review = bool(item.get("needs_review"))
            candidate = self.candidate_repository.add_candidate(
                conn,
                workspace_slug=workspace_slug,
                person_id=item.get("person_id"),
                source_id=int(item["source_id"]),
                conversation_id=item.get("conversation_id"),
                session_id=item.get("session_id"),
                chunk_kind=item.get("chunk_kind", "conversation"),
                chunk_id=item.get("chunk_id"),
                domain=item["domain"],
                category=item["category"],
                subcategory=item.get("subcategory", ""),
                canonical_key=item["canonical_key"],
                payload=item["payload"],
                summary=item["summary"],
                confidence=float(item["confidence"]),
                reason=reason,
                extracted_at=item.get("occurred_at") or None,
            )
            candidate = self.candidate_repository.update_candidate_evidence(
                conn,
                candidate_id=int(candidate["id"]),
                evidence=item.get("evidence", []),
            )
            if candidate["candidate_status"] == "published":
                persisted.append(candidate)
                continue
            if needs_review:
                candidate = self.candidate_repository.mark_candidate_status(
                    conn,
                    candidate_id=int(candidate["id"]),
                    candidate_status="needs_review",
                    reason=reason,
                )
                candidate = self.candidate_repository.update_candidate_evidence(
                    conn,
                    candidate_id=int(candidate["id"]),
                    evidence=item.get("evidence", []),
                )
                self.review_repository.enqueue(
                    conn,
                    workspace_slug=workspace_slug,
                    person_id=candidate.get("person_id"),
                    candidate=candidate,
                    reason=reason or "needs_review",
                    candidate_id=int(candidate["id"]),
                )
            else:
                candidate = self.candidate_repository.mark_candidate_status(
                    conn,
                    candidate_id=int(candidate["id"]),
                    candidate_status="validated_candidate",
                    reason=reason,
                )
            persisted.append(candidate)
        return persisted

    def list_candidates(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        candidate_status: str | None = None,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return self.candidate_repository.list_candidates(
            conn,
            workspace_slug=workspace_slug,
            person_id=person_id,
            candidate_status=candidate_status,
            domain=domain,
            limit=limit,
        )

    def reextract_for_speaker_resolution(
        self,
        conn,
        *,
        workspace_slug: str,
        conversation_id: int,
    ) -> list[dict]:
        return self.extract_from_conversation(
            conn,
            workspace_slug=workspace_slug,
            conversation_id=conversation_id,
        )

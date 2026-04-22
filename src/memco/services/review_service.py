from __future__ import annotations

from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.review_repository import ReviewRepository

MIN_REVIEW_APPROVED_CONFIDENCE = 0.6


class ReviewService:
    def __init__(
        self,
        review_repository: ReviewRepository | None = None,
        candidate_repository: CandidateRepository | None = None,
    ) -> None:
        self.review_repository = review_repository or ReviewRepository()
        self.candidate_repository = candidate_repository or CandidateRepository()

    def resolve(self, conn, *, queue_id: int, decision: str, reason: str = "") -> dict:
        return self.resolve_with_person(
            conn,
            queue_id=queue_id,
            decision=decision,
            reason=reason,
        )

    def list_items(
        self,
        conn,
        *,
        workspace_slug: str,
        status: str | None = None,
        person_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        return self.review_repository.list_items(
            conn,
            workspace_slug=workspace_slug,
            status=status,
            person_id=person_id,
            limit=limit,
        )

    def resolve_with_person(
        self,
        conn,
        *,
        queue_id: int,
        decision: str,
        reason: str = "",
        candidate_person_id: int | None = None,
        candidate_target_person_id: int | None = None,
    ) -> dict:
        row = self.review_repository.resolve(
            conn,
            queue_id=queue_id,
            decision=decision,
            reason=reason,
        )
        candidate_id = row.get("candidate_id")
        if candidate_id is not None:
            current_candidate = self.candidate_repository.get_candidate(
                conn,
                candidate_id=int(candidate_id),
            )
            if decision == "approved" and candidate_person_id is not None:
                self.candidate_repository.update_candidate_person(
                    conn,
                    candidate_id=int(candidate_id),
                    person_id=candidate_person_id,
                    reason=reason,
                )
            if decision == "approved" and candidate_target_person_id is not None:
                payload = dict(current_candidate.get("payload") or {})
                payload["target_person_id"] = int(candidate_target_person_id)
                self.candidate_repository.update_candidate_payload(
                    conn,
                    candidate_id=int(candidate_id),
                    payload=payload,
                    reason=reason,
                )
                current_candidate = self.candidate_repository.get_candidate(
                    conn,
                    candidate_id=int(candidate_id),
                )
            if decision == "approved" and float(current_candidate.get("confidence", 0.0)) < MIN_REVIEW_APPROVED_CONFIDENCE:
                self.candidate_repository.update_candidate_confidence(
                    conn,
                    candidate_id=int(candidate_id),
                    confidence=MIN_REVIEW_APPROVED_CONFIDENCE,
                )
            next_status = "validated_candidate" if decision == "approved" else "rejected"
            self.candidate_repository.mark_candidate_status(
                conn,
                candidate_id=int(candidate_id),
                candidate_status=next_status,
                reason=reason,
            )
            row["candidate"] = self.candidate_repository.get_candidate(
                conn,
                candidate_id=int(candidate_id),
            )
        return row

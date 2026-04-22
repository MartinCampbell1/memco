from __future__ import annotations

from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.review_repository import ReviewRepository

MIN_REVIEW_APPROVED_CONFIDENCE = 0.6


class ReviewService:
    ALLOWED_DECISIONS = {"approved", "rejected"}
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
        items = self.review_repository.list_items(
            conn,
            workspace_slug=workspace_slug,
            status=status,
            person_id=person_id,
            limit=limit,
        )
        return [self._enrich_review_item(item) for item in items]

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
        if decision not in self.ALLOWED_DECISIONS:
            raise ValueError("decision must be one of: approved, rejected")
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
        row["resolution_reason"] = reason
        return self._enrich_review_item(row)

    def _reason_codes(self, reason: str) -> list[str]:
        if not reason:
            return []
        return [part.strip() for part in reason.split(",") if part.strip()]

    def _decision_summary(self, *, status: str, candidate: dict | None, reason: str) -> str:
        candidate_label = ""
        if candidate is not None:
            candidate_label = candidate.get("summary") or candidate.get("canonical_key") or "candidate"
        if status == "approved":
            return f"approved: {candidate_label}".strip()
        if status == "rejected":
            return f"rejected: {candidate_label}".strip()
        if status == "pending":
            return f"pending: {candidate_label}".strip()
        return status

    def _enrich_review_item(self, item: dict) -> dict:
        candidate = item.get("candidate")
        enriched = dict(item)
        candidate_reason = ""
        candidate_domain = ""
        candidate_summary = ""
        candidate_status = ""
        if isinstance(candidate, dict):
            candidate_reason = str(item.get("reason") or candidate.get("reason") or "")
            candidate_domain = str(candidate.get("domain") or "")
            candidate_summary = str(candidate.get("summary") or candidate.get("canonical_key") or "")
            candidate_status = str(candidate.get("candidate_status") or "")
        enriched["candidate_reason"] = candidate_reason
        enriched["candidate_reason_codes"] = self._reason_codes(candidate_reason or str(item.get("reason") or ""))
        enriched["candidate_domain"] = candidate_domain
        enriched["candidate_summary"] = candidate_summary
        enriched["candidate_status"] = candidate_status
        enriched["decision_summary"] = self._decision_summary(
            status=str(item.get("status") or ""),
            candidate=candidate if isinstance(candidate, dict) else None,
            reason=str(item.get("reason") or ""),
        )
        if str(item.get("status") or "") == "pending":
            enriched["next_action_hint"] = "review-resolve approved|rejected"
        elif str(item.get("status") or "") == "approved":
            enriched["next_action_hint"] = "candidate-publish or inspect candidate"
        else:
            enriched["next_action_hint"] = "inspect candidate or queue history"
        return enriched

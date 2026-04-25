from __future__ import annotations

from memco.repositories.fact_repository import FactRepository
from memco.services.review_service import ReviewService


class MemoryExplorerService:
    def __init__(
        self,
        *,
        fact_repository: FactRepository | None = None,
        review_service: ReviewService | None = None,
    ) -> None:
        self.fact_repository = fact_repository or FactRepository()
        self.review_service = review_service or ReviewService()

    def snapshot(
        self,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        fact_status: str | None = None,
        domain: str | None = None,
        review_status: str | None = "pending",
        limit: int = 50,
    ) -> dict:
        facts = self.fact_repository.list_facts(
            conn,
            workspace_slug=workspace_slug,
            person_id=person_id,
            status=fact_status,
            domain=domain,
            limit=limit,
        )
        changes = self.fact_repository.list_operations(
            conn,
            workspace_slug=workspace_slug,
            person_id=person_id,
            domain=domain,
            limit=limit,
        )
        review = self.review_service.dashboard(
            conn,
            workspace_slug=workspace_slug,
            status=review_status,
            person_id=person_id,
            domain=domain,
            limit=limit,
        )
        return {
            "artifact_type": "memory_explorer_snapshot",
            "workspace": workspace_slug,
            "filters": {
                "person_id": person_id,
                "fact_status": fact_status,
                "domain": domain,
                "review_status": review_status,
                "limit": limit,
            },
            "counts": {
                "facts": len(facts),
                "changes": len(changes),
                "review_items": int(review.get("summary", {}).get("review_item_count") or 0),
                "candidate_cards": len(review.get("candidate_cards") or []),
            },
            "facts": facts,
            "changes": changes,
            "review": review,
            "action_hints": {
                "inspect_evidence": "Facts include evidence; narrow with `memory-explorer --person-slug ... --domain ...`.",
                "approve_review": "Use `review-resolve approved --latest-review --publish` for the newest matching review item.",
                "reject_candidate": "Use `candidate-reject --latest-candidate` or `review-resolve rejected --latest-review`.",
                "rollback_change": "Use `fact-rollback --latest-operation` or pass an operation id from `changes`.",
                "filter_by_domain": "Use `memory-explorer --domain biography|work|preferences|social_circle|experiences`.",
            },
        }

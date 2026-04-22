from __future__ import annotations

from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository


class ConsolidationService:
    def __init__(self, fact_repository: FactRepository | None = None) -> None:
        self.fact_repository = fact_repository or FactRepository()

    def add_fact(
        self,
        conn,
        payload: MemoryFactInput,
        *,
        locator: dict | None = None,
        source_chunk_id: int | None = None,
        source_segment_id: int | None = None,
        session_id: int | None = None,
    ) -> dict:
        person_id = payload.person_id
        if person_id is None:
            person_id = self.fact_repository.resolve_person_id(
                conn,
                workspace_slug=payload.workspace,
                person_slug=payload.person_slug,
            )
        return self.fact_repository.add_fact(
            conn,
            workspace_slug=payload.workspace,
            person_id=person_id,
            domain=payload.domain,
            category=payload.category,
            subcategory=payload.subcategory,
            canonical_key=payload.canonical_key,
            payload=payload.payload,
            summary=payload.summary,
            source_kind=payload.source_kind,
            confidence=payload.confidence,
            observed_at=payload.observed_at,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            event_at=payload.event_at,
            source_id=payload.source_id,
            quote_text=payload.quote_text,
            source_chunk_id=source_chunk_id,
            source_segment_id=source_segment_id,
            session_id=session_id,
            locator=locator,
        )

    def mark_deleted(self, conn, *, fact_id: int, reason: str = "") -> dict:
        return self.fact_repository.mark_fact_status(
            conn,
            fact_id=fact_id,
            status="deleted",
            reason=reason or "deleted",
        )

    def restore(self, conn, *, fact_id: int, reason: str = "") -> dict:
        return self.fact_repository.mark_fact_status(
            conn,
            fact_id=fact_id,
            status="active",
            reason=reason or "restored",
        )

    def rollback(self, conn, *, operation_id: int, reason: str = "") -> dict:
        return self.fact_repository.rollback_operation(
            conn,
            operation_id=operation_id,
            reason=reason or "rolled back",
        )

from __future__ import annotations

from memco.models.memory_fact import MemoryFactInput
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.services.consolidation_service import ConsolidationService


MIN_PUBLISH_CONFIDENCE = 0.6


class PublishService:
    def __init__(
        self,
        candidate_repository: CandidateRepository | None = None,
        fact_repository: FactRepository | None = None,
        consolidation_service: ConsolidationService | None = None,
    ) -> None:
        self.candidate_repository = candidate_repository or CandidateRepository()
        self.fact_repository = fact_repository or FactRepository()
        self.consolidation_service = consolidation_service or ConsolidationService(
            fact_repository=self.fact_repository
        )

    def publish_candidate(self, conn, *, workspace_slug: str, candidate_id: int) -> dict:
        candidate = self.candidate_repository.get_candidate(conn, candidate_id=candidate_id)
        workspace_row = conn.execute(
            "SELECT workspace_id FROM fact_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        workspace_id = self.fact_repository.ensure_workspace(conn, workspace_slug)
        if workspace_row is None or int(workspace_row["workspace_id"]) != workspace_id:
            raise ValueError("Cannot publish candidate outside the requested workspace scope")
        if candidate["candidate_status"] == "published" and candidate.get("publish_target_fact_id"):
            return {
                "candidate": candidate,
                "fact": self.fact_repository.get_fact(
                    conn, fact_id=int(candidate["publish_target_fact_id"])
                ),
            }
        if candidate["candidate_status"] != "validated_candidate":
            raise ValueError(f"Cannot publish candidate with status {candidate['candidate_status']}")
        if not candidate.get("canonical_key"):
            raise ValueError("Cannot publish candidate without canonical_key")
        if not candidate.get("payload"):
            raise ValueError("Cannot publish candidate without payload")
        if candidate["person_id"] is None:
            raise ValueError("Cannot publish unresolved candidate")
        if float(candidate.get("confidence", 0.0)) < MIN_PUBLISH_CONFIDENCE:
            raise ValueError("Cannot publish candidate below confidence threshold")
        evidence_items = candidate.get("evidence") or []
        if not evidence_items:
            raise ValueError("Cannot publish candidate without evidence")
        primary_evidence = evidence_items[0]
        if not (primary_evidence.get("source_segment_ids") or []):
            raise ValueError("Cannot publish candidate without source-segment provenance")
        if candidate["domain"] == "social_circle" and candidate["payload"].get("target_person_id") is None:
            raise ValueError("Cannot publish social_circle candidate with unresolved hard conflict")
        payload = MemoryFactInput(
            workspace=workspace_slug,
            person_id=int(candidate["person_id"]),
            domain=candidate["domain"],
            category=candidate["category"],
            subcategory=candidate["subcategory"],
            canonical_key=candidate["canonical_key"],
            payload=candidate["payload"],
            summary=candidate["summary"],
            confidence=float(candidate["confidence"]),
            observed_at=candidate["extracted_at"],
            source_id=int(candidate["source_id"]),
            quote_text=primary_evidence.get("quote") or candidate["summary"],
        )
        locator = {
            "message_ids": primary_evidence.get("message_ids", []),
            "source_segment_ids": primary_evidence.get("source_segment_ids", []),
            "chunk_kind": primary_evidence.get("chunk_kind", candidate.get("chunk_kind", "conversation")),
            "candidate_id": int(candidate["id"]),
        }
        source_segment_ids = primary_evidence.get("source_segment_ids") or []
        fact = self.consolidation_service.add_fact(
            conn,
            payload,
            locator=locator,
            source_chunk_id=candidate.get("chunk_id"),
            source_segment_id=int(source_segment_ids[0]) if source_segment_ids else None,
        )
        updated_candidate = self.candidate_repository.mark_candidate_status(
            conn,
            candidate_id=candidate_id,
            candidate_status="published",
            publish_target_fact_id=int(fact["id"]),
        )
        return {"candidate": updated_candidate, "fact": fact}

    def reject_candidate(self, conn, *, candidate_id: int, reason: str = "") -> dict:
        return self.candidate_repository.mark_candidate_status(
            conn,
            candidate_id=candidate_id,
            candidate_status="rejected",
            reason=reason,
        )

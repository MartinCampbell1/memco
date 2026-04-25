from __future__ import annotations

import json

from memco.consolidation import get_policy
from memco.extractors.base import validate_candidate_payload
from memco.models.memory_fact import MemoryFactInput
from memco.models.relationships import FAMILY_SOCIAL_BRIDGE_RELATION_TYPES, canonical_relation_type
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.services.consolidation_service import ConsolidationService
from memco.utils import slugify


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

    def _social_mirror_for_family_fact(
        self,
        *,
        workspace_slug: str,
        candidate: dict,
        source_fact: dict,
    ) -> MemoryFactInput | None:
        if candidate.get("domain") != "biography" or candidate.get("category") != "family":
            return None
        candidate_payload = candidate.get("payload") or {}
        relation = canonical_relation_type(str(candidate_payload.get("relation") or candidate.get("subcategory") or ""))
        target_label = str(candidate_payload.get("target_label") or candidate_payload.get("name") or "").strip()
        if relation not in FAMILY_SOCIAL_BRIDGE_RELATION_TYPES or not target_label:
            return None
        person_key = str(candidate.get("canonical_key") or "").split(":", 1)[0] or "person"
        mirror_payload = {
            "relation": relation,
            "target_label": target_label,
            "target_person_id": candidate_payload.get("target_person_id"),
            "is_current": bool(candidate_payload.get("is_current", True)),
            "mirrored_from_domain": "biography",
            "mirrored_from_category": "family",
            "mirrored_from_fact_id": int(source_fact["id"]),
        }
        return MemoryFactInput(
            workspace=workspace_slug,
            person_id=int(candidate["person_id"]),
            domain="social_circle",
            category=relation,
            subcategory="",
            canonical_key=f"{person_key}:social_circle:{relation}:{slugify(target_label)}",
            payload=mirror_payload,
            summary=source_fact["summary"],
            source_kind="derived_mirror",
            confidence=float(source_fact["confidence"]),
            observed_at=source_fact["observed_at"],
            valid_from=str(source_fact.get("valid_from") or ""),
            valid_to=str(source_fact.get("valid_to") or ""),
            event_at=str(source_fact.get("event_at") or ""),
            source_id=int(candidate["source_id"]),
            quote_text=source_fact["evidence"][0]["quote_text"] if source_fact.get("evidence") else candidate["summary"],
        )

    def _ensure_social_target_person_id(self, conn, *, workspace_slug: str, target_label: str) -> int:
        target_label = target_label.strip()
        if not target_label:
            raise ValueError("Cannot publish social_circle candidate without target_label")
        target_slug = slugify(target_label)
        try:
            return self.fact_repository.resolve_person_id(
                conn,
                workspace_slug=workspace_slug,
                person_slug=target_slug,
            )
        except ValueError:
            person = self.fact_repository.upsert_person(
                conn,
                workspace_slug=workspace_slug,
                display_name=target_label,
                slug=target_slug,
                person_type="human",
                aliases=[target_label],
            )
            return int(person["id"])

    def _resolve_social_target_for_publish(self, conn, *, workspace_slug: str, candidate: dict) -> dict:
        if candidate.get("domain") != "social_circle":
            return candidate
        payload = dict(candidate.get("payload") or {})
        if payload.get("target_person_id") is not None:
            return candidate
        target_label = str(payload.get("target_label") or "").strip()
        target_person_id = self._ensure_social_target_person_id(
            conn,
            workspace_slug=workspace_slug,
            target_label=target_label,
        )
        payload["target_person_id"] = target_person_id
        return self.candidate_repository.update_candidate_payload(
            conn,
            candidate_id=int(candidate["id"]),
            payload=payload,
            reason="auto-resolved social target from target_label",
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
        validate_candidate_payload(
            domain=str(candidate["domain"]),
            category=str(candidate["category"]),
            payload=candidate["payload"],
        )
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
        candidate = self._resolve_social_target_for_publish(
            conn,
            workspace_slug=workspace_slug,
            candidate=candidate,
        )
        publish_block_reason = get_policy(str(candidate["domain"])).publish_block_reason(
            category=str(candidate["category"]),
            payload=candidate["payload"],
        )
        if publish_block_reason is not None:
            raise ValueError(publish_block_reason)
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
            valid_from=str((candidate.get("payload") or {}).get("valid_from") or ""),
            event_at=str((candidate.get("payload") or {}).get("event_at") or ""),
            source_id=int(candidate["source_id"]),
            quote_text=primary_evidence.get("quote") or candidate["summary"],
        )
        locator = {
            "message_ids": primary_evidence.get("message_ids", []),
            "source_segment_ids": primary_evidence.get("source_segment_ids", []),
            "session_ids": primary_evidence.get("session_ids", []),
            "chunk_kind": primary_evidence.get("chunk_kind", candidate.get("chunk_kind", "conversation")),
            "candidate_id": int(candidate["id"]),
        }
        for key in ("attribution_method", "attribution_confidence", "source_type"):
            if key in primary_evidence:
                locator[key] = primary_evidence[key]
        source_segment_ids = primary_evidence.get("source_segment_ids") or []
        session_ids = primary_evidence.get("session_ids") or []
        if source_segment_ids:
            segment = SourceRepository().get_segment(conn, segment_id=int(source_segment_ids[0]))
            if segment is not None:
                segment_locator = json.loads(segment.get("locator_json") or "{}")
                if isinstance(segment_locator, dict) and segment_locator:
                    locator["source_segment_locator"] = segment_locator
                locator["source_segment_type"] = segment.get("segment_type") or ""
        fact = self.consolidation_service.add_fact(
            conn,
            payload,
            locator=locator,
            source_chunk_id=candidate.get("chunk_id"),
            source_segment_id=int(source_segment_ids[0]) if source_segment_ids else None,
            session_id=int(session_ids[0]) if session_ids else candidate.get("session_id"),
        )
        mirrored_fact = None
        mirror_payload = self._social_mirror_for_family_fact(
            workspace_slug=workspace_slug,
            candidate=candidate,
            source_fact=fact,
        )
        if mirror_payload is not None:
            mirror_locator = {
                **locator,
                "mirrored_from_fact_id": int(fact["id"]),
                "mirror_kind": "biography_family_to_social_circle",
            }
            mirrored_fact = self.consolidation_service.add_fact(
                conn,
                mirror_payload,
                locator=mirror_locator,
                source_chunk_id=candidate.get("chunk_id"),
                source_segment_id=int(source_segment_ids[0]) if source_segment_ids else None,
                session_id=int(session_ids[0]) if session_ids else candidate.get("session_id"),
            )
        updated_candidate = self.candidate_repository.mark_candidate_status(
            conn,
            candidate_id=candidate_id,
            candidate_status="published",
            publish_target_fact_id=int(fact["id"]),
        )
        result = {"candidate": updated_candidate, "fact": fact}
        if mirrored_fact is not None:
            result["mirrored_fact"] = mirrored_fact
        return result

    def reject_candidate(self, conn, *, candidate_id: int, reason: str = "") -> dict:
        return self.candidate_repository.mark_candidate_status(
            conn,
            candidate_id=candidate_id,
            candidate_status="rejected",
            reason=reason,
        )

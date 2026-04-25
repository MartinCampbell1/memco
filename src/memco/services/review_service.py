from __future__ import annotations

from memco.consolidation import get_policy
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.review_repository import ReviewRepository

MIN_REVIEW_APPROVED_CONFIDENCE = 0.6


class ReviewService:
    ALLOWED_DECISIONS = {"approved", "rejected"}
    def __init__(
        self,
        review_repository: ReviewRepository | None = None,
        candidate_repository: CandidateRepository | None = None,
        fact_repository: FactRepository | None = None,
    ) -> None:
        self.review_repository = review_repository or ReviewRepository()
        self.candidate_repository = candidate_repository or CandidateRepository()
        self.fact_repository = fact_repository or FactRepository()

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
        domain: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        items = self.review_repository.list_items(
            conn,
            workspace_slug=workspace_slug,
            status=status,
            person_id=person_id,
            domain=domain,
            limit=limit,
        )
        return [self._enrich_review_item(item) for item in items]

    def dashboard(
        self,
        conn,
        *,
        workspace_slug: str,
        status: str | None = "pending",
        person_id: int | None = None,
        domain: str | None = None,
        limit: int = 50,
        low_confidence_threshold: float = MIN_REVIEW_APPROVED_CONFIDENCE,
    ) -> dict:
        review_items = self.list_items(
            conn,
            workspace_slug=workspace_slug,
            status=status,
            person_id=person_id,
            domain=domain,
            limit=limit,
        )
        candidates = self.candidate_repository.list_candidates(
            conn,
            workspace_slug=workspace_slug,
            person_id=person_id,
            domain=domain,
            limit=limit,
        )
        candidates_by_id: dict[int, dict] = {
            int(candidate["id"]): candidate
            for candidate in candidates
        }
        for item in review_items:
            candidate = item.get("candidate")
            if isinstance(candidate, dict) and candidate.get("id") is not None:
                candidates_by_id[int(candidate["id"])] = candidate
        candidate_cards = [
            self._candidate_card(
                conn,
                workspace_slug=workspace_slug,
                candidate=candidate,
                low_confidence_threshold=low_confidence_threshold,
            )
            for candidate in sorted(candidates_by_id.values(), key=lambda item: int(item["id"]), reverse=True)
        ]
        cards_by_candidate_id = {card["candidate_id"]: card for card in candidate_cards}
        enriched_review_items = []
        for item in review_items:
            candidate_id = item.get("candidate_id")
            enriched_review_items.append(
                {
                    "queue_id": int(item["id"]),
                    "status": item["status"],
                    "reason": item.get("reason", ""),
                    "candidate_id": int(candidate_id) if candidate_id is not None else None,
                    "candidate_summary": item.get("candidate_summary", ""),
                    "candidate_reason_codes": item.get("candidate_reason_codes", []),
                    "next_action_hint": item.get("next_action_hint", ""),
                    "candidate_card": cards_by_candidate_id.get(int(candidate_id)) if candidate_id is not None else None,
                }
            )
        return {
            "workspace": workspace_slug,
            "filters": {
                "status": status,
                "person_id": person_id,
                "domain": domain,
                "limit": limit,
                "low_confidence_threshold": low_confidence_threshold,
            },
            "summary": self._dashboard_summary(
                review_items=enriched_review_items,
                candidate_cards=candidate_cards,
            ),
            "review_items": enriched_review_items,
            "candidate_cards": candidate_cards,
        }

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

    def _dashboard_summary(self, *, review_items: list[dict], candidate_cards: list[dict]) -> dict:
        def count_flag(flag: str) -> int:
            return sum(1 for card in candidate_cards if flag in card["flags"])

        return {
            "review_item_count": len(review_items),
            "candidate_card_count": len(candidate_cards),
            "needs_review_count": count_flag("needs_review"),
            "low_confidence_count": count_flag("low_confidence"),
            "sensitive_count": count_flag("sensitive"),
            "psychometrics_inference_count": count_flag("psychometrics_inference"),
            "proposed_merge_count": sum(
                1 for card in candidate_cards if card["consolidation_preview"]["action"] == "merge_duplicate"
            ),
            "proposed_supersede_count": sum(
                1 for card in candidate_cards if card["consolidation_preview"]["action"] == "supersede_existing"
            ),
        }

    def _candidate_card(
        self,
        conn,
        *,
        workspace_slug: str,
        candidate: dict,
        low_confidence_threshold: float,
    ) -> dict:
        domain = str(candidate.get("domain") or "")
        category = str(candidate.get("category") or "")
        sensitivity, visibility = self.fact_repository.classify_fact_access(domain=domain, category=category)
        flags = self._candidate_flags(
            candidate=candidate,
            sensitivity=sensitivity,
            visibility=visibility,
            low_confidence_threshold=low_confidence_threshold,
        )
        return {
            "candidate_id": int(candidate["id"]),
            "status": candidate.get("candidate_status", ""),
            "domain": domain,
            "category": category,
            "canonical_key": candidate.get("canonical_key", ""),
            "summary": candidate.get("summary", ""),
            "confidence": float(candidate.get("confidence", 0.0)),
            "reason_codes": self._reason_codes(str(candidate.get("reason") or "")),
            "person_id": candidate.get("person_id"),
            "sensitivity": sensitivity,
            "visibility": visibility,
            "flags": flags,
            "evidence_preview": self._evidence_preview(candidate.get("evidence") or []),
            "consolidation_preview": self._consolidation_preview(
                conn,
                workspace_slug=workspace_slug,
                candidate=candidate,
            ),
            "next_action_hint": self._candidate_next_action_hint(candidate=candidate, flags=flags),
        }

    def _candidate_flags(
        self,
        *,
        candidate: dict,
        sensitivity: str,
        visibility: str,
        low_confidence_threshold: float,
    ) -> list[str]:
        flags: list[str] = []
        if candidate.get("candidate_status") == "needs_review":
            flags.append("needs_review")
        if float(candidate.get("confidence", 0.0)) < low_confidence_threshold:
            flags.append("low_confidence")
        if sensitivity == "high" or visibility == "owner_only":
            flags.append("sensitive")
        if candidate.get("domain") == "psychometrics":
            flags.append("psychometrics_inference")
        if not candidate.get("evidence"):
            flags.append("missing_evidence")
        return flags

    def _evidence_preview(self, evidence_items: list[dict], *, limit: int = 3) -> list[dict]:
        preview = []
        for item in evidence_items[:limit]:
            quote = str(item.get("quote") or item.get("quote_text") or "")
            preview.append(
                {
                    "quote": quote[:240],
                    "message_ids": item.get("message_ids", []),
                    "source_segment_ids": item.get("source_segment_ids", []),
                    "session_ids": item.get("session_ids", []),
                    "chunk_kind": item.get("chunk_kind", ""),
                }
            )
        return preview

    def _consolidation_preview(self, conn, *, workspace_slug: str, candidate: dict) -> dict:
        person_id = candidate.get("person_id")
        if person_id is None:
            return {"action": "needs_person_resolution", "target_fact_id": None, "reason": "candidate has no person_id"}
        payload = candidate.get("payload") or {}
        domain = str(candidate.get("domain") or "")
        category = str(candidate.get("category") or "")
        canonical_key = str(candidate.get("canonical_key") or "")
        if not payload or not canonical_key:
            return {"action": "not_publishable", "target_fact_id": None, "reason": "candidate is missing payload or canonical_key"}
        semantic_payload = self.fact_repository._semantic_payload(
            payload=payload,
            observed_at=str(candidate.get("extracted_at") or ""),
            valid_from=str(payload.get("valid_from") or ""),
            valid_to=str(payload.get("valid_to") or ""),
            event_at=str(payload.get("event_at") or ""),
        )
        duplicate = self.fact_repository.find_duplicate_fact(
            conn,
            workspace_slug=workspace_slug,
            person_id=int(person_id),
            domain=domain,
            category=category,
            canonical_key=canonical_key,
            payload=payload,
            semantic_payload=semantic_payload,
        )
        if duplicate is not None:
            return {
                "action": "merge_duplicate",
                "target_fact_id": int(duplicate["id"]),
                "reason": "semantic duplicate in the same domain/category",
            }
        current = self.fact_repository.find_current_fact(
            conn,
            workspace_slug=workspace_slug,
            person_id=int(person_id),
            domain=domain,
            category=category,
            canonical_key=canonical_key,
            payload=payload,
        )
        decision = get_policy(domain).resolve(
            category=category,
            canonical_key=canonical_key,
            payload=payload,
            observed_at=str(candidate.get("extracted_at") or ""),
            existing_fact=current,
        )
        return {
            "action": decision.action,
            "target_fact_id": int(current["id"]) if current is not None else None,
            "reason": decision.reason,
            "conflict_kind": decision.conflict_kind,
        }

    def _candidate_next_action_hint(self, *, candidate: dict, flags: list[str]) -> str:
        if "needs_review" in flags:
            return "review-resolve approved|rejected"
        if candidate.get("candidate_status") == "validated_candidate":
            return "candidate-publish or candidate-reject"
        return "candidate-list or review-list"

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

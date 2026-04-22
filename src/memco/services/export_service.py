from __future__ import annotations

from collections import defaultdict

from memco.api.deps import build_internal_actor
from memco.models.retrieval import DetailPolicy
from memco.repositories.fact_repository import FactRepository
from memco.services.retrieval_service import RetrievalService
from memco.utils import isoformat_z


class ExportService:
    def __init__(
        self,
        *,
        fact_repository: FactRepository | None = None,
        retrieval_service: RetrievalService | None = None,
    ) -> None:
        self.fact_repository = fact_repository or FactRepository()
        self.retrieval_service = retrieval_service or RetrievalService()

    def _resolve_actor(self, settings, actor):
        if actor is not None:
            return actor
        return build_internal_actor(settings, actor_id="dev-owner")

    def _can_view_sensitive(self, actor) -> bool:
        if actor is None:
            return False
        return actor.actor_type in {"owner", "system"} and actor.can_view_sensitive

    def _sanitize_fact(self, fact: dict, *, include_sensitive: bool, detail_policy: DetailPolicy) -> dict | None:
        if not include_sensitive and (fact.get("visibility") == "owner_only" or fact.get("sensitivity") == "high"):
            return None
        evidence = fact.get("evidence") or []
        source_ids = sorted({int(item["source_id"]) for item in evidence if item.get("source_id") is not None})
        session_ids = sorted({int(item["session_id"]) for item in evidence if item.get("session_id") is not None})
        support_types = sorted({str(item["support_type"]) for item in evidence if item.get("support_type")})
        base = {
            "id": int(fact["id"]),
            "domain": fact["domain"],
            "category": fact["category"],
            "subcategory": fact.get("subcategory", ""),
            "canonical_key": fact["canonical_key"],
            "summary": fact["summary"],
            "status": fact["status"],
            "confidence": fact["confidence"],
        }
        if detail_policy == "core_only":
            return base
        base.update(
            {
                "payload": fact["payload"],
                "observed_at": fact["observed_at"],
                "valid_from": fact.get("valid_from", ""),
                "valid_to": fact.get("valid_to", ""),
                "event_at": fact.get("event_at", ""),
                "sensitivity": fact.get("sensitivity", "normal"),
                "visibility": fact.get("visibility", "standard"),
                "evidence_summary": {
                    "count": len(evidence),
                    "source_ids": source_ids,
                    "session_ids": session_ids,
                    "support_types": support_types,
                },
            }
        )
        if detail_policy == "exhaustive":
            base["evidence"] = [
                {
                    "evidence_id": int(item["evidence_id"]),
                    "source_id": int(item["source_id"]) if item.get("source_id") is not None else None,
                    "source_segment_id": int(item["source_segment_id"]) if item.get("source_segment_id") is not None else None,
                    "session_id": int(item["session_id"]) if item.get("session_id") is not None else None,
                    "support_type": item.get("support_type", ""),
                    "source_confidence": item.get("source_confidence"),
                    "locator_json": item.get("locator_json") or {},
                }
                for item in evidence
            ]
        return base

    def export_persona(
        self,
        settings,
        conn,
        *,
        workspace_slug: str,
        person_id: int | None = None,
        person_slug: str | None = None,
        domain: str | None = None,
        detail_policy: DetailPolicy = "balanced",
        actor=None,
    ) -> dict:
        resolved_actor = self._resolve_actor(settings, actor)
        resolved_person_id = self.fact_repository.resolve_person_id(
            conn,
            workspace_slug=workspace_slug,
            person_id=person_id,
            person_slug=person_slug,
        )
        person = self.fact_repository.get_person(conn, workspace_slug=workspace_slug, person_id=resolved_person_id)
        if person is None:
            raise ValueError("Unknown person")
        facts = self.fact_repository.list_facts(
            conn,
            workspace_slug=workspace_slug,
            person_id=resolved_person_id,
            domain=domain,
            limit=1000,
        )
        include_sensitive = self._can_view_sensitive(resolved_actor)
        sanitized_facts = [
            fact
            for fact in (
                self._sanitize_fact(item, include_sensitive=include_sensitive, detail_policy=detail_policy)
                for item in facts
            )
            if fact is not None
        ]
        grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        domain_counts: dict[str, int] = defaultdict(int)
        source_ids: set[int] = {
            int(item["source_id"])
            for fact in facts
            for item in (fact.get("evidence") or [])
            if item.get("source_id") is not None
        }
        for fact in sanitized_facts:
            grouped[fact["domain"]][fact["category"]].append(fact)
            domain_counts[fact["domain"]] += 1
        domains = {
            domain_name: {
                category_name: items
                for category_name, items in sorted(category_map.items())
            }
            for domain_name, category_map in sorted(grouped.items())
        }
        return {
            "artifact_type": "persona_export",
            "exported_at": isoformat_z(),
            "workspace": workspace_slug,
            "person": {
                "id": int(person["id"]),
                "slug": person["slug"],
                "display_name": person["display_name"],
                "person_type": person["person_type"],
                "status": person["status"],
                "aliases": [alias["alias"] for alias in person.get("aliases", [])],
            },
            "filters": {
                "domain": domain,
                "sensitive_facts_included": include_sensitive,
                "detail_policy": detail_policy,
            },
            "counts": {
                "fact_count": len(sanitized_facts),
                "source_count": len(source_ids),
                "domain_counts": dict(sorted(domain_counts.items())),
            },
            "domains": domains,
        }

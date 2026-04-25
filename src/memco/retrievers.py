from __future__ import annotations

from dataclasses import dataclass, field

from memco.repositories.retrieval_repository import RetrievalRepository


@dataclass(frozen=True)
class DomainRetriever:
    domain: str
    payload_fields: dict[str, tuple[str, ...]]
    synonyms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    temporal_fields: tuple[str, ...] = ("observed_at", "valid_from", "valid_to", "event_at")
    false_premise_claim_checks: tuple[str, ...] = ("name",)
    current_history_behavior: str = "active_current_superseded_history"
    factual: bool = True

    def category_sequence(self, category: str | None) -> tuple[str | None, ...]:
        if category:
            return (category, None)
        return (None,)

    def retrieve(
        self,
        repository: RetrievalRepository,
        conn,
        *,
        workspace_slug: str,
        person_id: int,
        query: str,
        category: str | None,
        temporal_mode: str,
        limit: int,
    ) -> list[dict]:
        if not self.factual:
            return []
        seen_categories: set[str | None] = set()
        for candidate_category in self.category_sequence(category):
            if candidate_category in seen_categories:
                continue
            seen_categories.add(candidate_category)
            hits = repository.retrieve_facts(
                conn,
                workspace_slug=workspace_slug,
                person_id=person_id,
                query=query,
                domain=self.domain,
                category=candidate_category,
                temporal_mode=temporal_mode,
                limit=limit,
            )
            if hits:
                return hits
        return []


class BiographyRetriever(DomainRetriever):
    def __init__(self) -> None:
        super().__init__(
            domain="biography",
            payload_fields={
                "residence": ("city", "place"),
                "family": ("relation", "name", "target_label", "target_person_id"),
                "origin": ("place", "city"),
                "education": ("institution", "field"),
            },
            synonyms={"residence": ("home", "live", "lives", "city"), "family": ("sister", "brother", "spouse", "parent")},
            false_premise_claim_checks=("name", "location", "relation"),
        )


class PreferenceRetriever(DomainRetriever):
    def __init__(self) -> None:
        super().__init__(
            domain="preferences",
            payload_fields={"preference": ("value", "polarity", "preference_domain", "preference_category", "reason")},
            synonyms={"preference": ("like", "prefer", "dislike", "favorite")},
            false_premise_claim_checks=("preference",),
        )


class SocialCircleRetriever(DomainRetriever):
    def __init__(self) -> None:
        super().__init__(
            domain="social_circle",
            payload_fields={
                "relationship": ("relation", "target_label", "target_person_id", "aliases"),
                "relationship_event": ("target_label", "target_person_id", "event", "context"),
            },
            synonyms={"relationship": ("friend", "sister", "brother", "partner", "colleague")},
            false_premise_claim_checks=("relation", "relation_target", "name"),
        )


class WorkRetriever(DomainRetriever):
    WORK_FALLBACKS: dict[str, tuple[str, ...]] = {
        "tool": ("skill", "project", "employment", "org", "role", "engagement"),
        "skill": ("tool", "project", "employment", "org", "role", "engagement"),
        "project": ("engagement", "tool", "skill", "employment", "org", "role"),
    }

    def __init__(self) -> None:
        super().__init__(
            domain="work",
            payload_fields={
                "employment": ("title", "role", "org", "client", "status", "team"),
                "org": ("org", "client", "status"),
                "role": ("role", "title", "status"),
                "project": ("project", "role", "org", "client", "outcomes"),
                "skill": ("skill",),
                "tool": ("tool",),
            },
            synonyms={"employment": ("work", "job", "company"), "tool": ("uses", "stack"), "project": ("built", "launched")},
            false_premise_claim_checks=("employer", "tool", "skill", "project"),
        )

    def category_sequence(self, category: str | None) -> tuple[str | None, ...]:
        if category is None:
            return (None,)
        return (category, *self.WORK_FALLBACKS.get(category, ("employment", "role", "org", "project", "skill", "tool", "engagement")), None)


class ExperienceRetriever(DomainRetriever):
    def __init__(self) -> None:
        super().__init__(
            domain="experiences",
            payload_fields={"event": ("event", "summary", "event_at", "date_range", "location", "participants", "outcome", "lesson")},
            synonyms={"event": ("attended", "visited", "accident", "trip", "conference")},
            false_premise_claim_checks=("event", "date", "location", "name"),
        )


class PsychometricsRetriever(DomainRetriever):
    def __init__(self) -> None:
        super().__init__(
            domain="psychometrics",
            payload_fields={"trait": ("framework", "trait", "score", "evidence")},
            synonyms={"trait": ("personality", "trait", "profile")},
            false_premise_claim_checks=(),
            current_history_behavior="non_factual_context_only",
            factual=False,
        )


def build_domain_retrievers() -> dict[str, DomainRetriever]:
    retrievers: list[DomainRetriever] = [
        BiographyRetriever(),
        PreferenceRetriever(),
        SocialCircleRetriever(),
        WorkRetriever(),
        ExperienceRetriever(),
        PsychometricsRetriever(),
    ]
    return {retriever.domain: retriever for retriever in retrievers}

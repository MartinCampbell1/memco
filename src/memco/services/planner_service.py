from __future__ import annotations

import re

from memco.models.retrieval import RetrievalClaimCheck, RetrievalDomainPlan, RetrievalPlan, RetrievalRequest


QUESTION_PATTERNS: list[tuple[re.Pattern[str], str, str | None, str]] = [
    (re.compile(r"\bwhere\b.*\bliv", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"\bliv(?:e|es|ing)\b|\bmoved?\s+to\b", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"\bprefer\b|\blike\b|\bfavorit", re.IGNORECASE), "preferences", "preference", "question asks about preferences"),
    (re.compile(r"\bwork\b|\bjob\b|\bcareer\b|\bprofession\b|\bdo for work\b", re.IGNORECASE), "work", "employment", "question asks about work"),
    (re.compile(r"\bskill\b|\buse\b|\bknow\b", re.IGNORECASE), "work", "skill", "question asks about skills"),
    (re.compile(r"\battend\b|\bvisit\b|\bwent\b|\btrip\b|\btravel\b|\bexperience\b", re.IGNORECASE), "experiences", "event", "question asks about experiences"),
    (
        re.compile(r"\bfriend\b|\bsister\b|\bbrother\b|\bmother\b|\bfather\b|\bpartner\b|\bwife\b|\bhusband\b|\bcolleague\b",
            re.IGNORECASE),
        "social_circle",
        None,
        "question asks about a relationship",
    ),
]

TEMPORAL_HISTORY_RE = re.compile(r"\b(before|previously|used to|used to be|earlier|formerly|past|previous)\b", re.IGNORECASE)
TEMPORAL_CURRENT_RE = re.compile(r"\b(now|currently|current|today|these days)\b", re.IGNORECASE)
TEMPORAL_WHEN_RE = re.compile(r"\bwhen\b", re.IGNORECASE)
NAME_CLAIM_RE = re.compile(r"\b(?:named|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")
WORK_AT_RE = re.compile(r"\bwork(?:s)?\s+at\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)")


class PlannerService:
    def plan(self, payload: RetrievalRequest) -> RetrievalPlan:
        if payload.domain or payload.category:
            return RetrievalPlan(
                question_type=self._question_type(payload.query, temporal_mode=payload.temporal_mode),
                domain_queries=[
                    RetrievalDomainPlan(
                        domain=payload.domain or "unknown",
                        category=payload.category,
                        reason="explicit retrieval filters from caller",
                    )
                ],
                temporal_mode=payload.temporal_mode,
                temporal_anchor=self._temporal_anchor(payload.query),
                false_premise_risk=self._false_premise_risk(payload.query),
                requires_temporal_reasoning=self._requires_temporal_reasoning(payload.query, payload.temporal_mode),
                claim_checks=self._claim_checks(payload.query),
            )

        domain_queries: list[RetrievalDomainPlan] = []
        seen: set[tuple[str, str | None]] = set()
        for pattern, domain, category, reason in QUESTION_PATTERNS:
            if not pattern.search(payload.query):
                continue
            key = (domain, category)
            if key in seen:
                continue
            domain_queries.append(
                RetrievalDomainPlan(
                    domain=domain,
                    category=category,
                    reason=reason,
                )
            )
            seen.add(key)

        if not domain_queries:
            domain_queries.append(
                RetrievalDomainPlan(
                    domain="biography",
                    category=None,
                    reason="default fallback for personal factual question",
                )
            )

        temporal_mode = payload.temporal_mode
        if temporal_mode == "auto":
            if TEMPORAL_HISTORY_RE.search(payload.query):
                temporal_mode = "history"
            elif TEMPORAL_CURRENT_RE.search(payload.query):
                temporal_mode = "current"

        return RetrievalPlan(
            question_type=self._question_type(payload.query, temporal_mode=temporal_mode),
            domain_queries=domain_queries,
            temporal_mode=temporal_mode,
            temporal_anchor=self._temporal_anchor(payload.query),
            false_premise_risk=self._false_premise_risk(payload.query),
            requires_temporal_reasoning=self._requires_temporal_reasoning(payload.query, temporal_mode),
            requires_cross_domain_synthesis=len({item.domain for item in domain_queries}) > 1,
            claim_checks=self._claim_checks(payload.query),
        )

    def _question_type(self, query: str, *, temporal_mode: str) -> str:
        if " and " in query.lower():
            return "multi_hop"
        if temporal_mode == "history" or TEMPORAL_WHEN_RE.search(query):
            return "temporal"
        return "single_hop"

    def _temporal_anchor(self, query: str) -> str:
        if TEMPORAL_HISTORY_RE.search(query):
            return "history"
        if TEMPORAL_CURRENT_RE.search(query):
            return "current"
        return ""

    def _requires_temporal_reasoning(self, query: str, temporal_mode: str) -> bool:
        return temporal_mode == "history" or bool(TEMPORAL_WHEN_RE.search(query))

    def _false_premise_risk(self, query: str) -> str:
        if TEMPORAL_WHEN_RE.search(query) or NAME_CLAIM_RE.search(query):
            return "high"
        if " and " in query.lower():
            return "medium"
        return "low"

    def _claim_checks(self, query: str) -> list[RetrievalClaimCheck]:
        checks: list[RetrievalClaimCheck] = []
        lower_query = query.lower()
        relation_terms = [
            "sister",
            "brother",
            "mother",
            "father",
            "partner",
            "wife",
            "husband",
            "friend",
            "colleague",
        ]
        for term in relation_terms:
            if term in lower_query:
                checks.append(RetrievalClaimCheck(label="relationship", value=term, claim_type="relation"))
        for match in NAME_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="named_entity", value=match.strip(), claim_type="name"))
        for match in WORK_AT_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="employer", value=match.strip(), claim_type="name"))
        return checks

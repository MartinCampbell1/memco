from __future__ import annotations

import json
import re

from memco.llm_usage import LLMUsageEvent, LLMUsageTracker, estimate_token_count
from memco.models.retrieval import RetrievalClaimCheck, RetrievalDomainPlan, RetrievalPlan, RetrievalRequest


QUESTION_PATTERNS: list[tuple[re.Pattern[str], str, str | None, str]] = [
    (re.compile(r"\bwhere\b.*\bliv", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"\bliv(?:e|es|ing)\b|\bmoved?\s+to\b", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"(?:где|куда).*(?:жив|переех)", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"жив(?:у|ет|ут|ешь)|переехал(?:а|и)?\s+в", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"\bprefer(?:s)?\b|\blike(?:s)?\b|\bfavorit", re.IGNORECASE), "preferences", "preference", "question asks about preferences"),
    (re.compile(r"предпоч|нрав|любл", re.IGNORECASE), "preferences", "preference", "question asks about preferences"),
    (re.compile(r"\bwork\b|\bjob\b|\bcareer\b|\bprofession\b|\bdo for work\b", re.IGNORECASE), "work", "employment", "question asks about work"),
    (re.compile(r"работ|професси|карьер|чем .*занима", re.IGNORECASE), "work", "employment", "question asks about work"),
    (re.compile(r"\bskill\b|\buse\b|\bknow\b", re.IGNORECASE), "work", "skill", "question asks about skills"),
    (re.compile(r"уме|использ|знаю", re.IGNORECASE), "work", "skill", "question asks about skills"),
    (re.compile(r"\battend(?:ed)?\b|\bvisit(?:ed)?\b|\bwent\b|\btrip\b|\btravel(?:ed)?\b|\bexperience\b", re.IGNORECASE), "experiences", "event", "question asks about experiences"),
    (re.compile(r"посет|был на|была на|ходил на|ходила на|поездк|путешеств", re.IGNORECASE), "experiences", "event", "question asks about experiences"),
    (
        re.compile(r"\bfriend\b|\bsister\b|\bbrother\b|\bmother\b|\bfather\b|\bpartner\b|\bwife\b|\bhusband\b|\bcolleague\b",
            re.IGNORECASE),
        "social_circle",
        None,
        "question asks about a relationship",
    ),
    (
        re.compile(r"друг|сестр|брат|мать|отец|партнер|жена|муж|коллег", re.IGNORECASE),
        "social_circle",
        None,
        "question asks about a relationship",
    ),
]

RELATION_TERMS = (
    "sister",
    "brother",
    "mother",
    "father",
    "partner",
    "wife",
    "husband",
    "friend",
    "colleague",
    "сестра",
    "брат",
    "мать",
    "отец",
    "партнер",
    "жена",
    "муж",
    "друг",
    "коллега",
)
TEMPORAL_HISTORY_RE = re.compile(r"\b(before|previously|used to|used to be|earlier|formerly|past|previous|раньше|ранее|прежде|до|прошл)\b", re.IGNORECASE)
TEMPORAL_CURRENT_RE = re.compile(r"\b(now|currently|current|today|these days|сейчас|теперь)\b", re.IGNORECASE)
TEMPORAL_WHEN_RE = re.compile(r"\b(when|когда)\b", re.IGNORECASE)
NAME_CLAIM_RE = re.compile(r"\b(?:named|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")
PROPER_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
WORK_AT_RE = re.compile(r"\b(?:work(?:s)?\s+at|работ(?:аю|ает|ал|ала)?\s+в)\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)", re.IGNORECASE)
LOCATION_CLAIM_RE = re.compile(
    r"\b(?:live|lives|living|based|located|moved?|move|жив(?:у|ет|ут|ешь)|переехал(?:а|и)?)\s+(?:in|to|в)\s+(?P<value>[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)",
    re.IGNORECASE,
)
PREFERENCE_CLAIM_RE = re.compile(
    r"\b(?:prefer|like|love|hate|dislike|предпочита(?:ю|ет)|нрав(?:ится|ятс?я)|люблю|не люблю)\s+(?P<value>[^?.!,]+?)(?:\s+(?:now|currently|today|сейчас|теперь))?(?:\?|$| and | but )",
    re.IGNORECASE,
)
EVENT_CLAIM_RE = re.compile(
    r"\b(?:(?i:attend|attended|visit|visited|went\s+to|travel(?:ed)?\s+to|посетил(?:а|и)?|был на|была на|ходил на|ходила на))\s+"
    r"(?P<value>[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)"
    r"(?:\s+in\s+(?:19|20)\d{2}\b)?",
)
DATE_CLAIM_RE = re.compile(r"\b((?:19|20)\d{2})\b")
RELATION_TARGET_RE = re.compile(
    r"\b(?:is|was)\s+(?P<target>[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)\s+[A-Z][A-Za-z0-9&.\-]+'s\s+(?:"
    + "|".join(RELATION_TERMS)
    + r")\b",
    re.IGNORECASE,
)
BEFORE_TARGET_RE = re.compile(r"\bbefore\s+([A-Z][A-Za-z0-9&.\-]+)\b", re.IGNORECASE)


class PlannerService:
    def __init__(self, usage_tracker: LLMUsageTracker | None = None) -> None:
        self.usage_tracker = usage_tracker

    def _record_usage(self, *, query: str, plan: RetrievalPlan) -> None:
        if self.usage_tracker is None:
            return
        payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        self.usage_tracker.record(
            LLMUsageEvent(
                provider="deterministic",
                model="rule-based-planner",
                operation="plan",
                input_tokens=estimate_token_count(query),
                output_tokens=estimate_token_count(payload),
                estimated_cost_usd=0.0,
                deterministic=True,
                metadata={"stage": "planner"},
            )
        )

    def plan(self, payload: RetrievalRequest) -> RetrievalPlan:
        temporal_mode = self._resolve_temporal_mode(payload.query, payload.temporal_mode)
        if payload.domain or payload.category:
            plan = RetrievalPlan(
                plan_version="v2",
                question_type=self._question_type(payload.query, temporal_mode=temporal_mode),
                domain_queries=[
                    RetrievalDomainPlan(
                        domain=payload.domain or "unknown",
                        category=payload.category,
                        field_query=payload.query,
                        reason="explicit retrieval filters from caller",
                    )
                ],
                temporal_mode=temporal_mode,
                temporal_anchor=self._temporal_anchor(payload.query),
                false_premise_risk=self._false_premise_risk(payload.query),
                requires_temporal_reasoning=self._requires_temporal_reasoning(payload.query, temporal_mode),
                claim_checks=self._claim_checks(payload.query, person_slug=payload.person_slug),
                support_expectation=self._support_expectation(payload.query, 1),
            )
            self._record_usage(query=payload.query, plan=plan)
            return plan

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
                    field_query=payload.query,
                    reason=reason,
                )
            )
            seen.add(key)

        if not domain_queries:
            domain_queries.append(
                RetrievalDomainPlan(
                    domain="biography",
                    category=None,
                    field_query=payload.query,
                    reason="default fallback for personal factual question",
                )
            )

        plan = RetrievalPlan(
            plan_version="v2",
            question_type=self._question_type(payload.query, temporal_mode=temporal_mode),
            domain_queries=domain_queries,
            temporal_mode=temporal_mode,
            temporal_anchor=self._temporal_anchor(payload.query),
            false_premise_risk=self._false_premise_risk(payload.query),
            requires_temporal_reasoning=self._requires_temporal_reasoning(payload.query, temporal_mode),
            requires_cross_domain_synthesis=len({item.domain for item in domain_queries}) > 1,
            claim_checks=self._claim_checks(payload.query, person_slug=payload.person_slug),
            support_expectation=self._support_expectation(payload.query, len({item.domain for item in domain_queries})),
        )
        self._record_usage(query=payload.query, plan=plan)
        return plan

    def _resolve_temporal_mode(self, query: str, requested_mode: str) -> str:
        temporal_mode = requested_mode
        if temporal_mode == "auto":
            if TEMPORAL_HISTORY_RE.search(query):
                temporal_mode = "history"
            elif TEMPORAL_CURRENT_RE.search(query):
                temporal_mode = "current"
            elif TEMPORAL_WHEN_RE.search(query):
                temporal_mode = "when"
        return temporal_mode

    def _question_type(self, query: str, *, temporal_mode: str) -> str:
        if " and " in query.lower():
            return "multi_hop"
        if temporal_mode == "history" or TEMPORAL_WHEN_RE.search(query):
            return "temporal"
        return "single_hop"

    def _temporal_anchor(self, query: str) -> str:
        before_match = BEFORE_TARGET_RE.search(query)
        if before_match:
            target = before_match.group(1).strip().replace(" ", "_").lower()
            return f"before_{target}"
        if TEMPORAL_HISTORY_RE.search(query):
            return "history"
        if TEMPORAL_CURRENT_RE.search(query):
            return "current"
        return ""

    def _requires_temporal_reasoning(self, query: str, temporal_mode: str) -> bool:
        return temporal_mode == "history" or bool(TEMPORAL_WHEN_RE.search(query))

    def _false_premise_risk(self, query: str) -> str:
        lower_query = query.lower()
        if (
            TEMPORAL_WHEN_RE.search(query)
            or NAME_CLAIM_RE.search(query)
            or WORK_AT_RE.search(query)
            or LOCATION_CLAIM_RE.search(query)
            or PREFERENCE_CLAIM_RE.search(query)
            or EVENT_CLAIM_RE.search(query)
            or DATE_CLAIM_RE.search(query)
        ):
            return "high"
        if any(term in lower_query for term in RELATION_TERMS) and (PROPER_NAME_RE.search(query) or RELATION_TARGET_RE.search(query)):
            return "high"
        if " and " in query.lower():
            return "medium"
        return "low"

    def _claim_checks(self, query: str, *, person_slug: str | None = None) -> list[RetrievalClaimCheck]:
        checks: list[RetrievalClaimCheck] = []
        lower_query = query.lower()
        for term in RELATION_TERMS:
            if term in lower_query:
                checks.append(RetrievalClaimCheck(label="relationship", value=term, claim_type="relation"))
        relation_target_match = RELATION_TARGET_RE.search(query)
        if relation_target_match:
            checks.append(
                RetrievalClaimCheck(
                    label="relation_target",
                    value=relation_target_match.group("target").strip(),
                    claim_type="relation_target",
                )
            )
        for match in NAME_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="named_entity", value=match.strip(), claim_type="name"))
        for match in WORK_AT_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="employer", value=match.strip(), claim_type="employer"))
        for match in LOCATION_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="location", value=match.strip(), claim_type="location"))
        for match in PREFERENCE_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="preference", value=match.strip(), claim_type="preference"))
        for match in EVENT_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="event", value=match.strip(), claim_type="event"))
        for match in DATE_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="date", value=match.strip(), claim_type="date"))
        temporal_anchor_target = None
        before_match = BEFORE_TARGET_RE.search(query)
        if before_match:
            temporal_anchor_target = before_match.group(1).strip()
        person_phrase = (person_slug or "").replace("-", " ").strip()
        quoted_names = [
            match.strip()
            for match in PROPER_NAME_RE.findall(query)
            if match.strip().lower() not in {"where", "what", "when", "does", "did", "who", "alice"}
        ]
        for match in quoted_names:
            words = match.split()
            if words and words[0].lower() in {"does", "did", "is", "what", "where", "when", "who", "tell", "show", "explain", "describe", "give"}:
                match = " ".join(words[1:]).strip()
            if not match:
                continue
            if temporal_anchor_target is not None and match == temporal_anchor_target:
                continue
            if person_phrase and match.lower() == person_phrase.lower():
                continue
            if person_phrase and " " in match and match.lower().endswith(person_phrase.lower()):
                continue
            if any(existing.value == match and existing.claim_type == "name" for existing in checks):
                continue
            checks.append(RetrievalClaimCheck(label="named_entity", value=match, claim_type="name"))
        return checks

    def _support_expectation(self, query: str, domain_count: int) -> str:
        if domain_count > 1:
            return "multi_domain_fact"
        if self._requires_temporal_reasoning(query, "history" if TEMPORAL_HISTORY_RE.search(query) else "auto"):
            return "temporal_fact"
        return "single_domain_fact"

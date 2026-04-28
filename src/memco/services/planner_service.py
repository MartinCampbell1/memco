from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from memco.extractors.base import DOMAIN_PROMPT_CONTRACTS
from memco.llm import LLMProvider
from memco.llm_usage import LLMUsageEvent, LLMUsageTracker, estimate_token_count
from memco.models.relationships import RELATION_QUERY_TERMS
from memco.models.retrieval import RetrievalClaimCheck, RetrievalDomainPlan, RetrievalPlan, RetrievalRequest
from memco.services.category_rag_service import build_field_constraints


QUESTION_PATTERNS: list[tuple[re.Pattern[str], str, str | None, str]] = [
    (re.compile(r"\bwhere\b.*\bliv", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"\bliv(?:e|es|ing)\b|\bmoved?\s+to\b", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"(?:где|куда).*(?:жив|переех)", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"жив(?:у|ет|ут|ешь)|переехал(?:а|и)?\s+в", re.IGNORECASE), "biography", "residence", "question asks about residence"),
    (re.compile(r"\bprefer(?:s)?\b|\blike(?:s)?\b|\bfavorit", re.IGNORECASE), "preferences", "preference", "question asks about preferences"),
    (re.compile(r"предпоч|нрав|любл", re.IGNORECASE), "preferences", "preference", "question asks about preferences"),
    (
        re.compile(r"\btool(?:s)?\b|\buse(?:s|d|ing)?\b(?!\s+to\b)|\bstack\b|\bsoftware\b|\btechnolog(?:y|ies)\b", re.IGNORECASE),
        "work",
        "tool",
        "question asks about work tools",
    ),
    (
        re.compile(r"\bproject(?:s)?\b|\bworked\s+on\b|\blaunched\b|\bshipped\b|\bbuilt\b|\bbuilding\b", re.IGNORECASE),
        "work",
        "project",
        "question asks about work projects",
    ),
    (
        re.compile(r"\bskill(?:s)?\b|\bcan\b|\bable\s+to\b", re.IGNORECASE),
        "work",
        "skill",
        "question asks about skills",
    ),
    (re.compile(r"\bwork\b|\bjob\b|\bcareer\b|\bprofession\b|\bdo for work\b", re.IGNORECASE), "work", "employment", "question asks about work"),
    (re.compile(r"работ|професси|карьер|чем .*занима", re.IGNORECASE), "work", "employment", "question asks about work"),
    (re.compile(r"уме|использ|знаю", re.IGNORECASE), "work", "skill", "question asks about skills"),
    (
        re.compile(r"\bwhat\s+happened\b|\bwhat\s+event\b|\bwhen\s+did\b.*\bhappen\b|\bwhat\s+changed\b|\bchanged\s+in\b|\bwhy\s+did\b.*\b(?:pause|stop|quit)\b|\bwhat\s+did\b.*\blearn\b|\blesson(?:s)?\b|\btakeaway(?:s)?\b|\boutcome(?:s)?\b|\baccident\b|\binjur(?:y|ed)\b|\btrip\b|\bexperience\b|\battend(?:ed)?\b|\bvisit(?:ed)?\b|\bwent\b|\btravel(?:ed)?\b",
            re.IGNORECASE),
        "experiences",
        "event",
        "question asks about experiences",
    ),
    (re.compile(r"посет|был на|была на|ходил на|ходила на|поездк|путешеств", re.IGNORECASE), "experiences", "event", "question asks about experiences"),
    (
        re.compile(
            r"\bknow(?:s)?\s+[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*\b|\bclose\s+people\b|\bclose\s+friend(?:s)?\b",
            re.IGNORECASE,
        ),
        "social_circle",
        None,
        "question asks about known or close people",
    ),
    (
        re.compile(r"\bfriend\b|\bsister\b|\bbrother\b|\bmother\b|\bfather\b|\bpartner\b|\bspouse\b|\bwife\b|\bhusband\b|\bcolleague\b|\bmanager\b|\bclient\b|\bacquaintance\b",
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

RELATION_TERMS = RELATION_QUERY_TERMS
TEMPORAL_HISTORY_RE = re.compile(r"\b(before|previously|used to|used to be|use to|earlier|formerly|past|previous|раньше|ранее|прежде|до|прошл)\b", re.IGNORECASE)
TEMPORAL_CURRENT_RE = re.compile(r"\b(now|currently|current|today|these days|still|сейчас|теперь)\b", re.IGNORECASE)
TEMPORAL_WHEN_RE = re.compile(r"\b(when|когда)\b", re.IGNORECASE)
NAME_CLAIM_RE = re.compile(r"\b(?:named|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")
PROPER_NAME_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]*(?:\s+(?:[A-Z][A-Za-z0-9&.\-]*|\d+))*\b")
WORK_AT_RE = re.compile(r"\b(?:work(?:s)?\s+at|работ(?:аю|ает|ал|ала)?\s+в)\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)", re.IGNORECASE)
WORK_TOOL_CLAIM_RE = re.compile(
    r"\b(?:use(?!\s+to\b)|uses|using|used(?!\s+to\b)|work(?:s)?\s+with|использ(?:ую|ует|овал|овала)|работ(?:аю|ает)\s+с)\s+(?P<value>[A-Z][A-Za-z0-9&.\-+#]*(?:\s+[A-Z][A-Za-z0-9&.\-+#]*)*)",
    re.IGNORECASE,
)
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
ACCIDENT_CLAIM_RE = re.compile(
    r"\b(?P<value>(?:(?:serious|major|minor|car|bike|bicycle|road|traffic|ski|the|an|a)\s+){0,4}accident)\b",
    re.IGNORECASE,
)
DATE_CLAIM_RE = re.compile(r"\b((?:19|20)\d{2})\b")
RELATION_TARGET_RE = re.compile(
    r"\b(?:is|was)\s+(?P<target>[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)\s+[A-Z][A-Za-z0-9&.\-]+'s\s+(?:"
    + "|".join(RELATION_TERMS)
    + r")\b",
    re.IGNORECASE,
)
BEFORE_TARGET_RE = re.compile(r"\bbefore\s+([A-Z][A-Za-z0-9&.\-]+)\b", re.IGNORECASE)
INTERROGATIVE_CLAIM_VALUE_RE = re.compile(
    r"^\s*(?:where|what|who|whom|whose|when|which|how|где|что|кто|когда|какой|какая|какие|как)\b",
    re.IGNORECASE,
)
CLAIM_VALUE_TOKEN_RE = re.compile(r"[a-zа-я0-9]+", re.IGNORECASE)
GENERIC_CLAIM_SLOT_WORDS = {
    "address",
    "city",
    "company",
    "country",
    "current",
    "date",
    "employer",
    "employment",
    "event",
    "home",
    "job",
    "live",
    "lives",
    "living",
    "location",
    "place",
    "preference",
    "preferences",
    "relationship",
    "residence",
    "role",
    "status",
    "time",
    "work",
    "адрес",
    "город",
    "дата",
    "живет",
    "место",
    "работа",
    "роль",
}
SUBJECT_SLOT_WORDS = {"a", "an", "her", "his", "in", "my", "of", "person", "s", "the", "their", "user"}


class LLMPlannerDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    categories: list[str] = Field(default_factory=list)
    field_query: str = ""
    reason: str = ""
    priority: int = 1


class LLMPlannerClaimCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    value: str
    must_be_supported: bool = True


class LLMPlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_person: str = ""
    domains: list[str | LLMPlannerDomain]
    claim_checks: list[LLMPlannerClaimCheck] = Field(default_factory=list)
    temporal_mode: str = "auto"
    false_premise_risk: str = "low"
    requires_temporal_reasoning: bool = False
    requires_cross_domain_synthesis: bool = False
    must_not_answer_without_evidence: bool = True
    question_type: str = "other"


class PlannerService:
    def __init__(
        self,
        usage_tracker: LLMUsageTracker | None = None,
        llm_provider: LLMProvider | None = None,
        use_llm: bool | None = None,
        llm_mode: str = "hybrid",
        fail_closed_on_provider_error: bool = True,
    ) -> None:
        self.usage_tracker = usage_tracker
        self.llm_provider = llm_provider
        self.use_llm = bool(llm_provider) if use_llm is None else use_llm
        self.llm_mode = llm_mode
        self.fail_closed_on_provider_error = fail_closed_on_provider_error

    def _record_usage(self, *, query: str, plan: RetrievalPlan, request: RetrievalRequest | None = None) -> None:
        if self.usage_tracker is None:
            return
        plan_payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        metadata = {"stage": "planner"}
        if request is not None:
            metadata.update(
                {
                    "person_slug": request.person_slug or "",
                    "domain": request.domain or "",
                    "category": request.category or "",
                }
            )
            if request.person_id is not None:
                metadata["person_id"] = request.person_id
        metadata["domains"] = sorted({item.domain for item in plan.domain_queries if item.domain})
        self.usage_tracker.record(
            LLMUsageEvent(
                provider="deterministic",
                model="rule-based-planner",
                operation="plan",
                input_tokens=estimate_token_count(query),
                output_tokens=estimate_token_count(plan_payload),
                estimated_cost_usd=0.0,
                deterministic=True,
                metadata=metadata,
            )
        )

    def plan(self, payload: RetrievalRequest) -> RetrievalPlan:
        if self.use_llm and self.llm_provider is not None and not payload.domain and not payload.category:
            deterministic_plan = self._rule_plan(payload, record_usage=False)
            if not self._should_use_provider(payload, deterministic_plan=deterministic_plan):
                self._record_usage(query=payload.query, plan=deterministic_plan, request=payload)
                return deterministic_plan
            provider_plan = self._try_provider_plan(payload)
            if provider_plan is not None:
                return provider_plan
            if self.fail_closed_on_provider_error:
                return self._fail_closed_plan(payload, reason="LLM planner provider failed or returned invalid output.")
            self._record_usage(query=payload.query, plan=deterministic_plan, request=payload)
            return deterministic_plan
        return self._rule_plan(payload)

    def _should_use_provider(self, payload: RetrievalRequest, *, deterministic_plan: RetrievalPlan) -> bool:
        if self.llm_mode == "always":
            return True
        if self.llm_mode != "hybrid":
            return False
        return (
            deterministic_plan.requires_cross_domain_synthesis
            or self._deterministic_plan_low_confidence(deterministic_plan)
        )

    def _deterministic_plan_low_confidence(self, plan: RetrievalPlan) -> bool:
        if plan.question_type == "other":
            return True
        if len(plan.domain_queries) != 1:
            return False
        query = plan.domain_queries[0]
        return (
            query.domain == "biography"
            and query.category is None
            and query.reason == "default fallback for personal factual question"
        )

    def _available_domain_schema(self) -> dict[str, list[str]]:
        return {domain: sorted(contract.categories.keys()) for domain, contract in DOMAIN_PROMPT_CONTRACTS.items()}

    def _planner_prompt(self, payload: RetrievalRequest) -> tuple[str, str]:
        output_schema = {
            "target_person": "string",
            "domains": [
                {
                    "domain": "one available domain",
                    "categories": ["optional available categories"],
                    "field_query": "query text scoped to this domain",
                    "reason": "short reason",
                    "priority": 1,
                }
            ],
            "claim_checks": [{"type": "employer|location|relation|name|preference|event|date", "value": "string", "must_be_supported": True}],
            "temporal_mode": "auto|current|history|when",
            "false_premise_risk": "low|medium|high",
            "requires_temporal_reasoning": False,
            "requires_cross_domain_synthesis": False,
            "must_not_answer_without_evidence": True,
            "question_type": "single_hop|multi_hop|temporal|other",
        }
        system_prompt = (
            "You are Memco's retrieval planner. Return only valid JSON matching the requested schema. "
            "Do not answer the user question. Do not invent personal facts. "
            "Plan retrieval domains and claim checks that must be supported by memory evidence."
        )
        prompt = json.dumps(
            {
                "task": "Plan memory retrieval for the query.",
                "query": payload.query,
                "target_person": payload.person_slug or payload.person_id or "",
                "available_domains": self._available_domain_schema(),
                "output_schema": output_schema,
                "rules": [
                    "Use only available domains and categories.",
                    "For multi-domain questions, include every required domain.",
                    "Every asserted premise in the query should appear as a claim_check with must_be_supported=true.",
                    "Set must_not_answer_without_evidence=true.",
                    "Return JSON only.",
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return system_prompt, prompt

    def _record_provider_usage(self, *, request: RetrievalRequest, response, plan: RetrievalPlan) -> None:
        if self.usage_tracker is None:
            return
        metadata = {
            "stage": "planner",
            "plan_version": plan.plan_version,
            "person_slug": request.person_slug or "",
            "domain": request.domain or "",
            "category": request.category or "",
            "domains": sorted({item.domain for item in plan.domain_queries if item.domain}),
        }
        if request.person_id is not None:
            metadata["person_id"] = request.person_id
        self.usage_tracker.record(
            LLMUsageEvent(
                provider=response.provider,
                model=response.model,
                operation="plan",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                estimated_cost_usd=response.usage.estimated_cost_usd,
                deterministic=False,
                metadata=metadata,
            )
        )

    def _try_provider_plan(self, payload: RetrievalRequest) -> RetrievalPlan | None:
        if self.llm_provider is None:
            return None
        try:
            system_prompt, prompt = self._planner_prompt(payload)
            response = self.llm_provider.complete_json(
                system_prompt=system_prompt,
                prompt=prompt,
                schema_name="memco_retrieval_plan_v1",
                metadata={"operation": "planner"},
            )
            output = LLMPlannerOutput.model_validate(response.content)
            plan = self._plan_from_provider_output(payload, output)
            self._record_provider_usage(request=payload, response=response, plan=plan)
            return plan
        except Exception:
            return None

    def _plan_from_provider_output(self, payload: RetrievalRequest, output: LLMPlannerOutput) -> RetrievalPlan:
        allowed_domains = self._available_domain_schema()
        temporal_mode = self._normalize_provider_temporal_mode(output.temporal_mode, payload.query, payload.temporal_mode)
        domain_queries: list[RetrievalDomainPlan] = []
        seen: set[tuple[str, str | None]] = set()
        for item in output.domains:
            domain_spec = self._provider_domain_spec(item)
            domain = domain_spec["domain"]
            if domain not in allowed_domains:
                raise ValueError(f"Unsupported planner domain: {domain}")
            categories = domain_spec["categories"] or [None]
            for category in categories:
                if category is not None and category not in allowed_domains[domain]:
                    raise ValueError(f"Unsupported planner category: {domain}/{category}")
                key = (domain, category)
                if key in seen:
                    continue
                domain_queries.append(
                    RetrievalDomainPlan(
                        domain=domain,
                        category=category,
                        field_query=domain_spec["field_query"] or payload.query,
                        reason=domain_spec["reason"] or "LLM planner selected this memory domain",
                    )
                )
                seen.add(key)
        if not domain_queries:
            raise ValueError("LLM planner returned no usable domain queries")
        domain_queries = self._guard_provider_domain_queries(payload=payload, domain_queries=domain_queries)
        domain_queries = self._attach_field_constraints(
            domain_queries,
            query=payload.query,
            temporal_mode=temporal_mode,
        )

        claim_checks = self._provider_claim_checks(output, person_slug=payload.person_slug)
        false_premise_risk = output.false_premise_risk if output.false_premise_risk in {"low", "medium", "high"} else self._false_premise_risk(payload.query)
        question_type = output.question_type if output.question_type in {"single_hop", "multi_hop", "temporal", "other"} else self._question_type(payload.query, temporal_mode=temporal_mode)
        return RetrievalPlan(
            plan_version="v2_llm",
            question_type=question_type,
            domain_queries=domain_queries,
            temporal_mode=temporal_mode,
            temporal_anchor=self._temporal_anchor(payload.query),
            false_premise_risk=false_premise_risk,
            requires_temporal_reasoning=output.requires_temporal_reasoning or self._requires_temporal_reasoning(payload.query, temporal_mode),
            requires_cross_domain_synthesis=output.requires_cross_domain_synthesis or len({item.domain for item in domain_queries}) > 1,
            must_not_answer_without_evidence=bool(output.must_not_answer_without_evidence),
            claim_checks=claim_checks or self._claim_checks(payload.query, person_slug=payload.person_slug),
            support_expectation=self._support_expectation(payload.query, len({item.domain for item in domain_queries})),
        )

    def _guard_provider_domain_queries(
        self,
        *,
        payload: RetrievalRequest,
        domain_queries: list[RetrievalDomainPlan],
    ) -> list[RetrievalDomainPlan]:
        temporal_mode = self._resolve_temporal_mode(payload.query, payload.temporal_mode)
        if self._question_type(payload.query, temporal_mode=temporal_mode) != "single_hop":
            return domain_queries
        for pattern, domain, category, reason in QUESTION_PATTERNS:
            if not pattern.search(payload.query):
                continue
            if any(item.domain == domain and item.category == category for item in domain_queries):
                return domain_queries
            return [
                RetrievalDomainPlan(
                    domain=domain,
                    category=category,
                    field_query=payload.query,
                    reason=f"{reason}; deterministic guard corrected provider domain plan",
                )
            ]
        return domain_queries

    def _provider_domain_spec(self, item: str | LLMPlannerDomain) -> dict[str, Any]:
        if isinstance(item, str):
            return {"domain": item.strip(), "categories": [], "field_query": "", "reason": ""}
        return {
            "domain": item.domain.strip(),
            "categories": [category.strip() for category in item.categories if category.strip()],
            "field_query": item.field_query.strip(),
            "reason": item.reason.strip(),
        }

    def _is_provider_answer_slot_claim(self, value: str, *, person_slug: str) -> bool:
        tokens = [token.lower() for token in CLAIM_VALUE_TOKEN_RE.findall(value)]
        if not tokens:
            return True
        subject_tokens = {token for token in re.split(r"[-_\s]+", person_slug.lower()) if token}
        filtered = [token for token in tokens if token not in subject_tokens and token not in SUBJECT_SLOT_WORDS]
        return bool(filtered) and all(token in GENERIC_CLAIM_SLOT_WORDS for token in filtered)

    def _provider_claim_checks(self, output: LLMPlannerOutput, *, person_slug: str) -> list[RetrievalClaimCheck]:
        checks: list[RetrievalClaimCheck] = []
        for check in output.claim_checks:
            value = check.value.strip()
            if not check.must_be_supported or not value:
                continue
            if INTERROGATIVE_CLAIM_VALUE_RE.search(value):
                continue
            if self._is_provider_answer_slot_claim(value, person_slug=person_slug):
                continue
            checks.append(RetrievalClaimCheck(label=check.type, value=value, claim_type=check.type))
        return checks

    def _normalize_provider_temporal_mode(self, temporal_mode: str, query: str, requested_mode: str) -> str:
        if temporal_mode in {"auto", "current", "history", "when"}:
            return self._resolve_temporal_mode(query, temporal_mode if requested_mode == "auto" else requested_mode)
        return self._resolve_temporal_mode(query, requested_mode)

    def _fail_closed_plan(self, payload: RetrievalRequest, *, reason: str) -> RetrievalPlan:
        temporal_mode = self._resolve_temporal_mode(payload.query, payload.temporal_mode)
        plan = RetrievalPlan(
            plan_version="v2_llm_fail_closed",
            question_type=self._question_type(payload.query, temporal_mode=temporal_mode),
            domain_queries=[],
            temporal_mode=temporal_mode,
            temporal_anchor=self._temporal_anchor(payload.query),
            false_premise_risk="high",
            requires_temporal_reasoning=self._requires_temporal_reasoning(payload.query, temporal_mode),
            requires_cross_domain_synthesis=False,
            must_not_answer_without_evidence=True,
            claim_checks=[
                RetrievalClaimCheck(label="planner_failure", value=reason, claim_type="planner_failure"),
            ],
            support_expectation="unsupported",
        )
        self._record_usage(query=payload.query, plan=plan, request=payload)
        return plan

    def _rule_plan(self, payload: RetrievalRequest, *, record_usage: bool = True) -> RetrievalPlan:
        temporal_mode = self._resolve_temporal_mode(payload.query, payload.temporal_mode)
        if payload.domain or payload.category:
            domain = payload.domain or "unknown"
            category = payload.category
            plan = RetrievalPlan(
                plan_version="v2",
                question_type=self._question_type(payload.query, temporal_mode=temporal_mode),
                domain_queries=[
                    RetrievalDomainPlan(
                        domain=domain,
                        category=category,
                        field_query=payload.query,
                        field_constraints=build_field_constraints(
                            query=payload.query,
                            domain=domain,
                            category=category,
                            temporal_mode=temporal_mode,
                        ),
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
            if record_usage:
                self._record_usage(query=payload.query, plan=plan, request=payload)
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
            if domain == "social_circle" and category is None:
                family_key = ("biography", "family")
                if family_key not in seen:
                    domain_queries.append(
                        RetrievalDomainPlan(
                            domain="biography",
                            category="family",
                            field_query=payload.query,
                            reason="family relationship fallback for relationship query",
                        )
                    )
                    seen.add(family_key)
            if domain == "work" and category == "employment":
                for fallback_category in ("role", "org", "project", "skill", "tool", "engagement"):
                    fallback_key = ("work", fallback_category)
                    if fallback_key in seen:
                        continue
                    domain_queries.append(
                        RetrievalDomainPlan(
                            domain="work",
                            category=fallback_category,
                            field_query=payload.query,
                            reason="generic work query searches multiple work categories",
                        )
                    )
                    seen.add(fallback_key)

        if not domain_queries:
            domain_queries.append(
                RetrievalDomainPlan(
                    domain="biography",
                    category=None,
                    field_query=payload.query,
                    reason="default fallback for personal factual question",
                )
            )
        domain_queries = self._attach_field_constraints(
            domain_queries,
            query=payload.query,
            temporal_mode=temporal_mode,
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
        if record_usage:
            self._record_usage(query=payload.query, plan=plan, request=payload)
        return plan

    def _attach_field_constraints(
        self,
        domain_queries: list[RetrievalDomainPlan],
        *,
        query: str,
        temporal_mode: str,
    ) -> list[RetrievalDomainPlan]:
        return [
            item.model_copy(
                update={
                    "field_constraints": item.field_constraints
                    or build_field_constraints(
                        query=query,
                        domain=item.domain,
                        category=item.category,
                        temporal_mode=temporal_mode,
                    )
                }
            )
            for item in domain_queries
        ]

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
        if any(self._contains_relation_term(lower_query, term) for term in RELATION_TERMS) and (
            PROPER_NAME_RE.search(query) or RELATION_TARGET_RE.search(query)
        ):
            return "high"
        if " and " in query.lower():
            return "medium"
        return "low"

    def _contains_relation_term(self, lower_query: str, term: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", lower_query, re.IGNORECASE) is not None

    def _claim_checks(self, query: str, *, person_slug: str | None = None) -> list[RetrievalClaimCheck]:
        checks: list[RetrievalClaimCheck] = []
        lower_query = query.lower()
        for term in RELATION_TERMS:
            if self._contains_relation_term(lower_query, term):
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
        for match in WORK_TOOL_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="tool", value=match.strip(), claim_type="tool"))
        for match in LOCATION_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="location", value=match.strip(), claim_type="location"))
        for match in PREFERENCE_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="preference", value=match.strip(), claim_type="preference"))
        for match in EVENT_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="event", value=match.strip(), claim_type="event"))
        for match in ACCIDENT_CLAIM_RE.findall(query):
            value = re.sub(r"^.*\b(?:in|had|have|has)\s+a\s+", "", match.strip(), flags=re.IGNORECASE)
            value = re.sub(r"^.*\b(?:have|has|had)\s+the\s+", "", value, flags=re.IGNORECASE)
            value = re.sub(r"^(?:an?|the)\s+(?=\w+\s+accident\b)", "", value, flags=re.IGNORECASE)
            if re.search(r"\b(?:have|has|had)\s+(?:an?|the)\s+accident\b", match, flags=re.IGNORECASE) or re.fullmatch(
                r"(?:an?|the)\s+accident",
                value,
                flags=re.IGNORECASE,
            ):
                value = "accident"
            checks.append(RetrievalClaimCheck(label="event", value=value, claim_type="event"))
        for match in DATE_CLAIM_RE.findall(query):
            checks.append(RetrievalClaimCheck(label="date", value=match.strip(), claim_type="date"))
        temporal_anchor_target = None
        before_match = BEFORE_TARGET_RE.search(query)
        if before_match:
            temporal_anchor_target = before_match.group(1).strip()
        person_phrase = (person_slug or "").replace("-", " ").strip()
        ignored_name_tokens = {
            "where",
            "what",
            "when",
            "does",
            "did",
            "who",
            "why",
            "alice",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        }
        quoted_names = []
        for match in PROPER_NAME_RE.findall(query):
            value = match.strip()
            first_word = value.split(maxsplit=1)[0].lower() if value else ""
            if value.lower() in ignored_name_tokens or first_word in ignored_name_tokens:
                continue
            quoted_names.append(value)
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

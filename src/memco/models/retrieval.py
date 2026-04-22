from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DetailPolicy = Literal["core_only", "balanced", "exhaustive"]


class RetrievalDomainPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    category: str | None = None
    field_query: str = ""
    reason: str = ""


class RetrievalClaimCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    claim_type: str = "term"


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: str = "other"
    plan_version: str = "v2"
    domain_queries: list[RetrievalDomainPlan] = Field(default_factory=list)
    temporal_mode: str = "auto"
    temporal_anchor: str = ""
    false_premise_risk: str = "low"
    requires_temporal_reasoning: bool = False
    requires_cross_domain_synthesis: bool = False
    must_not_answer_without_evidence: bool = True
    claim_checks: list[RetrievalClaimCheck] = Field(default_factory=list)
    support_expectation: str = "single_domain_fact"


class ActorContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    actor_type: Literal["system", "owner", "admin", "eval"]
    auth_token: str = ""
    allowed_person_ids: list[int] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    can_view_sensitive: bool = False


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    person_slug: str | None = None
    query: str
    domain: str | None = None
    category: str | None = None
    limit: int = 8
    include_fallback: bool = True
    temporal_mode: str = "auto"
    detail_policy: DetailPolicy = "balanced"
    actor: ActorContext | None = None


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: int
    domain: str
    category: str
    summary: str
    confidence: float
    score: float
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "active"
    source_kind: str = "fact"
    observed_at: str = ""
    valid_from: str = ""
    valid_to: str = ""
    event_at: str = ""


class RetrievalFallbackHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int
    chunk_kind: str
    chunk_id: int
    session_id: int | None = None
    text: str
    score: float


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    unsupported_premise_detected: bool = False
    support_level: str = "unsupported"
    detail_policy: DetailPolicy = "balanced"
    unsupported_claims: list[str] = Field(default_factory=list)
    hits: list[RetrievalHit] = Field(default_factory=list)
    fallback_hits: list[RetrievalFallbackHit] = Field(default_factory=list)
    planner: RetrievalPlan | None = None

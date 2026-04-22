from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from memco.models.retrieval import ActorContext


class PersonUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    display_name: str
    slug: str | None = None
    person_type: str = "human"
    aliases: list[str] = Field(default_factory=list)
    actor: ActorContext | None = None


class PersonAliasUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    person_slug: str | None = None
    alias: str
    alias_type: str = "name"
    actor: ActorContext | None = None


class PersonMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    from_person_id: int | None = None
    from_person_slug: str | None = None
    to_person_id: int | None = None
    to_person_slug: str | None = None
    reason: str = ""
    actor: ActorContext | None = None


class PersonRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    workspace_id: int
    slug: str
    display_name: str
    person_type: str
    status: str
    created_at: str
    updated_at: str


class MemoryFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    person_slug: str | None = None
    domain: str
    category: str
    subcategory: str = ""
    canonical_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    source_kind: str = "explicit"
    confidence: float = 0.5
    observed_at: str
    valid_from: str = ""
    valid_to: str = ""
    event_at: str = ""
    source_id: int
    quote_text: str = ""

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class MemoryFactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    workspace_id: int
    person_id: int
    domain: str
    category: str
    subcategory: str
    canonical_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str
    status: str
    sensitivity: str = "normal"
    visibility: str = "standard"
    confidence: float
    source_kind: str
    observed_at: str
    valid_from: str = ""
    valid_to: str = ""
    event_at: str = ""
    created_at: str
    updated_at: str


class FactCandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    workspace_id: int
    person_id: int | None = None
    source_id: int
    conversation_id: int | None = None
    session_id: int | None = None
    chunk_kind: str
    chunk_id: int | None = None
    domain: str
    category: str
    subcategory: str = ""
    canonical_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    confidence: float
    candidate_status: str
    publish_target_fact_id: int | None = None
    dedupe_key: str = ""
    reason: str = ""
    extracted_at: str
    reviewed_at: str = ""
    published_at: str = ""
    created_at: str
    updated_at: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)

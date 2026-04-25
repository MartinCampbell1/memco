from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from memco.models.retrieval import ActorContext


AgentMemoryContextMode = Literal["retrieval_only"]


class AgentMemoryContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    query: str
    person_slug: str
    mode: AgentMemoryContextMode = "retrieval_only"
    max_facts: int = Field(default=10, ge=1, le=50)
    include_evidence: bool = True
    temporal_mode: str = "auto"
    actor: ActorContext | None = None

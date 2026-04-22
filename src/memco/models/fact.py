from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from memco.models.retrieval import ActorContext


class FactListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    status: str | None = None
    domain: str | None = None
    limit: int = 50
    actor: ActorContext | None = None


class FactOperationListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    target_fact_id: int | None = None
    operation_type: str | None = None
    limit: int = 50
    actor: ActorContext | None = None


class FactStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: int
    reason: str = ""
    actor: ActorContext | None = None


class FactRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: int
    reason: str = ""
    actor: ActorContext | None = None

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from memco.models.retrieval import ActorContext


class ReviewListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    status: str | None = None
    person_id: int | None = None
    limit: int = 50
    actor: ActorContext | None = None


class ReviewResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_id: int
    decision: Literal["approved", "rejected"]
    reason: str = ""
    candidate_person_id: int | None = None
    candidate_target_person_id: int | None = None
    actor: ActorContext | None = None

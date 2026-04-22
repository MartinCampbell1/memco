from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReviewListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    status: str | None = None
    person_id: int | None = None
    limit: int = 50


class ReviewResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_id: int
    decision: str
    reason: str = ""
    candidate_person_id: int | None = None
    candidate_target_person_id: int | None = None

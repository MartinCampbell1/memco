from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from memco.models.retrieval import ActorContext


class PersonListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    status: str | None = None
    limit: int = 100
    actor: ActorContext | None = None

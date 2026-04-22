from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from memco.models.retrieval import ActorContext, DetailPolicy


class PersonaExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    person_slug: str | None = None
    domain: str | None = None
    detail_policy: DetailPolicy = "balanced"
    actor: ActorContext | None = None

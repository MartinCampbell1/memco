from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PersonListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    status: str | None = None
    limit: int = 100

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CandidateExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    conversation_id: int
    include_style: bool = False
    include_psychometrics: bool = False


class CandidateListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    person_id: int | None = None
    candidate_status: str | None = None
    domain: str | None = None
    limit: int = 20


class CandidatePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    candidate_id: int


class CandidateRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: int
    reason: str = ""

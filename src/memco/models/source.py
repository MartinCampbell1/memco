from __future__ import annotations

from memco.models.retrieval import ActorContext
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImportSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    source_type: str = "note"
    workspace: str = "default"
    actor: ActorContext | None = None


class ImportTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    source_type: str = "note"
    title: str = ""
    text: str
    actor: ActorContext | None = None


class IngestPipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    source_type: str = "json"
    path: str | None = None
    text: str | None = None
    title: str = ""
    person_display_name: str | None = None
    person_slug: str | None = None
    aliases: list[str] = Field(default_factory=list)
    conversation_uid: str = "main"
    include_style: bool = False
    include_psychometrics: bool = False
    actor: ActorContext | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        if bool(self.path) == bool(self.text):
            raise ValueError("Provide exactly one of `path` or `text`.")
        if (self.person_slug or self.aliases) and not self.person_display_name:
            raise ValueError("person_display_name is required when using person_slug or aliases.")
        return self


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    workspace_id: int
    source_path: str
    source_type: str
    origin_uri: str
    title: str
    sha256: str
    imported_at: str
    parsed_text: str
    meta: dict = Field(default_factory=dict)
    status: str


class ImportResult(BaseModel):
    source_id: int
    source_path: str
    normalized_path: str
    source_type: str
    title: str

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConversationMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = "unknown"
    speaker_label: str = ""
    occurred_at: str = ""
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


class ConversationImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    source_id: int
    conversation_uid: str = "main"
    title: str = ""


class ConversationImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: int
    source_id: int
    message_count: int
    chunk_count: int
    unresolved_speakers: list[str] = Field(default_factory=list)


class SpeakerMapRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_key: str
    raw_label: str
    person_id: int | None = None
    resolution_method: str
    confidence: float


class ConversationSpeakerListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    conversation_id: int


class ConversationSpeakerResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    conversation_id: int
    speaker_key: str
    person_id: int | None = None
    person_slug: str | None = None
    create_person_display_name: str | None = None
    create_person_slug: str | None = None

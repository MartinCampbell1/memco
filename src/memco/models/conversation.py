from __future__ import annotations

from typing import Literal
from typing import Any

from memco.models.retrieval import ActorContext
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
    actor: ActorContext | None = None


class ConversationImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: int
    source_id: int
    session_count: int
    message_count: int
    chunk_count: int
    unresolved_speakers: list[str] = Field(default_factory=list)


class MessageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int
    message_index: int
    speaker_label: str = ""
    person_id: int | None = None
    text: str
    occurred_at: str = ""
    source_segment_id: int | None = None
    session_id: int | None = None


class ExtractionChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: int
    chunk_kind: Literal["conversation", "source"]
    token_start: int | None = None
    token_end: int | None = None
    messages: list[MessageView] = Field(default_factory=list)
    text: str
    source_segment_ids: list[int] = Field(default_factory=list)
    overlap_prev: bool = False
    overlap_next: bool = False


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
    actor: ActorContext | None = None


class ConversationSpeakerResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "default"
    conversation_id: int
    speaker_key: str
    person_id: int | None = None
    person_slug: str | None = None
    create_person_display_name: str | None = None
    create_person_slug: str | None = None
    actor: ActorContext | None = None

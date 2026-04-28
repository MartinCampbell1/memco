from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NormalizedTurn(BaseModel):
    sample_id: str
    session_id: str
    session_index: int
    session_datetime: str | None = None
    dia_id: str | int | None = None
    speaker_key: Literal["speaker_a", "speaker_b"] | str
    speaker_name: str
    text: str
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedConversation(BaseModel):
    sample_id: str
    speaker_a: str
    speaker_b: str
    turns: list[NormalizedTurn]
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedQuestion(BaseModel):
    question_id: str
    sample_id: str
    question: str
    gold_answer: str
    category: str | None = None
    target_speaker_key: str | None = None
    target_speaker_name: str | None = None
    target_resolution: str = "unknown"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class LoCoMoDataset(BaseModel):
    source_path: str
    dataset_sha256: str
    conversations: list[NormalizedConversation]
    questions: list[NormalizedQuestion]
    unknown_target_count: int = 0
    loader_warnings: list[str] = Field(default_factory=list)

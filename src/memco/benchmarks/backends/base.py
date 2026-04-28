from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from memco.benchmarks.models import NormalizedConversation, NormalizedQuestion


class BackendIngestResult(BaseModel):
    ok: bool
    backend_name: str
    sample_id: str
    elapsed_ms: float
    tokens: dict[str, Any] = Field(default_factory=dict)
    memory_stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BackendAnswerResult(BaseModel):
    ok: bool
    backend_name: str
    sample_id: str
    question_id: str
    answer: str
    elapsed_ms: float
    tokens: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    support_level: str | None = None
    refused: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class MemoryBackend(ABC):
    name: str

    @abstractmethod
    def reset_sample(self, sample_id: str) -> None:
        ...

    @abstractmethod
    def ingest_conversation(self, conversation: NormalizedConversation) -> BackendIngestResult:
        ...

    @abstractmethod
    def answer_question(self, question: NormalizedQuestion) -> BackendAnswerResult:
        ...

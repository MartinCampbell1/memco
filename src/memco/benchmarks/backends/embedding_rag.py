from __future__ import annotations

import math
from collections.abc import Callable
from time import monotonic

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend
from memco.benchmarks.backends.common import AnswerFn, build_answer_prompt, deterministic_answer, estimate_tokens, grouped_session_texts
from memco.benchmarks.models import NormalizedConversation, NormalizedQuestion
from memco.benchmarks.prompts import ANSWER_PROMPT_VERSION
from memco.benchmarks.testing import fake_embed

EmbedFn = Callable[[str], list[float]]


class EmbeddingRagBackend(MemoryBackend):
    name = "embedding_rag"
    version = "locomo-answer-v1"

    def __init__(
        self,
        *,
        answer_model: str = "fixture",
        embedding_model: str = "fixture-embedding",
        top_k: int = 3,
        chunk_unit: str = "session",
        answer_fn: AnswerFn | None = None,
        embed_fn: EmbedFn | None = None,
    ):
        if chunk_unit != "session":
            raise ValueError("embedding_rag default benchmark only supports session chunks")
        self.answer_model = answer_model
        self.embedding_model = embedding_model
        self.top_k = top_k
        self.chunk_unit = chunk_unit
        self.answer_fn = answer_fn
        self.embed_fn = embed_fn or fake_embed
        self._chunks: list[dict[str, object]] = []

    def reset_sample(self, sample_id: str) -> None:
        self._chunks = []

    def ingest_conversation(self, conversation: NormalizedConversation) -> BackendIngestResult:
        started = monotonic()
        self._chunks = []
        embedding_tokens = 0
        for session_id, session_text, turns in grouped_session_texts(conversation):
            embedding = self.embed_fn(session_text)
            embedding_tokens += estimate_tokens(session_text)
            self._chunks.append(
                {
                    "chunk_id": session_id,
                    "chunk_unit": self.chunk_unit,
                    "text": session_text,
                    "embedding": embedding,
                    "turn_count": len(turns),
                    "session_ids": sorted({turn.session_id for turn in turns}),
                }
            )
        return BackendIngestResult(
            ok=True,
            backend_name=self.name,
            sample_id=conversation.sample_id,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens={"embedding_input_tokens": embedding_tokens},
            memory_stats={"chunk_unit": self.chunk_unit, "chunk_count": len(self._chunks), "top_k": self.top_k},
        )

    def answer_question(self, question: NormalizedQuestion) -> BackendAnswerResult:
        started = monotonic()
        if not self._chunks:
            return BackendAnswerResult(
                ok=False,
                backend_name=self.name,
                sample_id=question.sample_id,
                question_id=question.question_id,
                answer="",
                elapsed_ms=(monotonic() - started) * 1000,
                error="conversation_not_ingested",
            )
        question_embedding = self.embed_fn(question.question)
        scored = sorted(
            (
                (_cosine(question_embedding, chunk["embedding"]), chunk)
                for chunk in self._chunks
                if isinstance(chunk.get("embedding"), list)
            ),
            key=lambda item: item[0],
            reverse=True,
        )[: self.top_k]
        retrieved = [
            {
                "chunk_id": str(chunk["chunk_id"]),
                "chunk_unit": str(chunk["chunk_unit"]),
                "score": score,
                "text": str(chunk["text"]),
                "turn_count": int(chunk["turn_count"]),
                "session_ids": chunk["session_ids"],
            }
            for score, chunk in scored
        ]
        context_text = "\n\n".join(item["text"] for item in retrieved)
        prompt = build_answer_prompt(
            question=question.question,
            target_speaker_name=question.target_speaker_name,
            context=context_text,
        )
        answer = deterministic_answer(question=question.question, context=context_text, answer_fn=self.answer_fn)
        return BackendAnswerResult(
            ok=True,
            backend_name=self.name,
            sample_id=question.sample_id,
            question_id=question.question_id,
            answer=answer,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens={
                "input_tokens": estimate_tokens(prompt),
                "output_tokens": estimate_tokens(answer),
                "context_tokens": estimate_tokens(context_text),
                "embedding_input_tokens": estimate_tokens(question.question),
            },
            evidence_ids=[item["chunk_id"] for item in retrieved],
            retrieved_context=retrieved,
            support_level="supported" if answer != "The information is not supported by the available memory." else "unsupported",
            refused=False,
            raw={
                "answer_model": self.answer_model,
                "embedding_model": self.embedding_model,
                "prompt_version": ANSWER_PROMPT_VERSION,
                "rag_top_k": self.top_k,
                "chunk_unit": self.chunk_unit,
            },
        )


def _cosine(left: list[float], right: object) -> float:
    if not isinstance(right, list):
        return 0.0
    pairs = list(zip(left, right))
    numerator = sum(float(a) * float(b) for a, b in pairs)
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left)) or 1.0
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right)) or 1.0
    return numerator / (left_norm * right_norm)

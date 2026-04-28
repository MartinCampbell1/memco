from __future__ import annotations

from time import monotonic

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend
from memco.benchmarks.backends.common import AnswerFn, build_answer_prompt, deterministic_answer, estimate_tokens, format_turns
from memco.benchmarks.models import NormalizedConversation, NormalizedQuestion
from memco.benchmarks.prompts import ANSWER_PROMPT_VERSION


class FullContextBackend(MemoryBackend):
    name = "full_context"
    version = "locomo-answer-v1"

    def __init__(self, *, answer_model: str = "fixture", answer_fn: AnswerFn | None = None):
        self.answer_model = answer_model
        self.answer_fn = answer_fn
        self._conversation: NormalizedConversation | None = None

    def reset_sample(self, sample_id: str) -> None:
        self._conversation = None

    def ingest_conversation(self, conversation: NormalizedConversation) -> BackendIngestResult:
        started = monotonic()
        self._conversation = conversation
        context = format_turns(conversation.turns)
        return BackendIngestResult(
            ok=True,
            backend_name=self.name,
            sample_id=conversation.sample_id,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens={"input_tokens": estimate_tokens(context), "context_tokens": estimate_tokens(context)},
            memory_stats={"turns": len(conversation.turns)},
        )

    def answer_question(self, question: NormalizedQuestion) -> BackendAnswerResult:
        started = monotonic()
        if self._conversation is None:
            return BackendAnswerResult(
                ok=False,
                backend_name=self.name,
                sample_id=question.sample_id,
                question_id=question.question_id,
                answer="",
                elapsed_ms=(monotonic() - started) * 1000,
                error="conversation_not_ingested",
            )
        context_text = format_turns(self._conversation.turns)
        prompt = build_answer_prompt(
            question=question.question,
            target_speaker_name=question.target_speaker_name,
            context=context_text,
        )
        answer = deterministic_answer(question=question.question, context=context_text, answer_fn=self.answer_fn)
        input_tokens = estimate_tokens(prompt)
        output_tokens = estimate_tokens(answer)
        return BackendAnswerResult(
            ok=True,
            backend_name=self.name,
            sample_id=question.sample_id,
            question_id=question.question_id,
            answer=answer,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "context_tokens": estimate_tokens(context_text),
            },
            evidence_ids=[],
            retrieved_context=[],
            support_level="supported" if answer != "The information is not supported by the available memory." else "unsupported",
            refused=False,
            raw={
                "answer_model": self.answer_model,
                "prompt_version": ANSWER_PROMPT_VERSION,
                "context": context_text,
            },
        )

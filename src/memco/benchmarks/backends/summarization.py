from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend
from memco.benchmarks.backends.common import (
    AnswerFn,
    build_answer_prompt,
    deterministic_answer,
    estimate_tokens,
    format_turns,
    grouped_session_texts,
)
from memco.benchmarks.models import NormalizedConversation, NormalizedQuestion
from memco.benchmarks.prompts import ANSWER_PROMPT_VERSION
from memco.benchmarks.testing import fake_summarize

SummaryFn = Callable[[str, str], str]


class SummarizationBackend(MemoryBackend):
    name = "summarization"
    version = "locomo-answer-v1"

    def __init__(
        self,
        *,
        answer_model: str = "fixture",
        answer_fn: AnswerFn | None = None,
        summarizer_fn: SummaryFn | None = None,
        recent_turns: int = 20,
    ):
        self.answer_model = answer_model
        self.answer_fn = answer_fn
        self.summarizer_fn = summarizer_fn or (
            lambda previous, session: fake_summarize(previous_summary=previous, session_text=session)
        )
        self.recent_turns = recent_turns
        self._conversation: NormalizedConversation | None = None
        self._summary = ""
        self._summary_input_tokens = 0
        self._summary_output_tokens = 0
        self._summary_calls = 0

    def reset_sample(self, sample_id: str) -> None:
        self._conversation = None
        self._summary = ""
        self._summary_input_tokens = 0
        self._summary_output_tokens = 0
        self._summary_calls = 0

    def ingest_conversation(self, conversation: NormalizedConversation) -> BackendIngestResult:
        started = monotonic()
        self._conversation = conversation
        summary = ""
        for _, session_text, _ in grouped_session_texts(conversation):
            prompt = f"Previous summary:\n{summary}\n\nNew session:\n{session_text}\n\nUpdate the summary."
            self._summary_input_tokens += estimate_tokens(prompt)
            summary = self.summarizer_fn(summary, session_text)
            self._summary_output_tokens += estimate_tokens(summary)
            self._summary_calls += 1
        self._summary = summary
        return BackendIngestResult(
            ok=True,
            backend_name=self.name,
            sample_id=conversation.sample_id,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens={
                "summarization_input_tokens": self._summary_input_tokens,
                "summarization_output_tokens": self._summary_output_tokens,
            },
            memory_stats={"summary_calls": self._summary_calls, "summary_tokens": estimate_tokens(self._summary)},
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
        recent_context = format_turns(self._conversation.turns[-self.recent_turns :])
        context_text = f"Rolling summary:\n{self._summary}\n\nRecent turns:\n{recent_context}".strip()
        prompt = build_answer_prompt(
            question=question.question,
            target_speaker_name=question.target_speaker_name,
            context=context_text,
        )
        answer = deterministic_answer(question=question.question, context=context_text, answer_fn=self.answer_fn)
        answer_input_tokens = estimate_tokens(prompt)
        answer_output_tokens = estimate_tokens(answer)
        return BackendAnswerResult(
            ok=True,
            backend_name=self.name,
            sample_id=question.sample_id,
            question_id=question.question_id,
            answer=answer,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens={
                "input_tokens": answer_input_tokens,
                "output_tokens": answer_output_tokens,
                "context_tokens": estimate_tokens(context_text),
                "summarization_input_tokens": self._summary_input_tokens,
                "summarization_output_tokens": self._summary_output_tokens,
                "amortized_summarization_tokens_per_question": self._summary_input_tokens
                + self._summary_output_tokens,
            },
            evidence_ids=[],
            retrieved_context=[],
            support_level="supported" if answer != "The information is not supported by the available memory." else "unsupported",
            refused=False,
            raw={
                "answer_model": self.answer_model,
                "prompt_version": ANSWER_PROMPT_VERSION,
                "summary_calls": self._summary_calls,
                "summary": self._summary,
                "context": context_text,
            },
        )

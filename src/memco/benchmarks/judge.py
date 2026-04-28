from __future__ import annotations

import json
import re
from collections.abc import Callable
from time import monotonic
from typing import Protocol

from pydantic import BaseModel, Field

from memco.benchmarks.backends.base import BackendAnswerResult
from memco.benchmarks.models import NormalizedQuestion
from memco.benchmarks.prompts import JUDGE_REPAIR_PROMPT, JUDGE_SYSTEM_PROMPT, JUDGE_USER_PROMPT
from memco.benchmarks.testing import fake_answer


JUDGE_ERROR_TYPES = {
    "none",
    "wrong_fact",
    "missing_fact",
    "unsupported_claim",
    "accepted_false_premise",
    "too_vague",
    "contradiction",
    "other",
}


class JudgeResult(BaseModel):
    ok: bool
    score: float | None = None
    label: str | None = None
    explanation: str | None = None
    error_type: str = "none"
    latency_ms: float = 0.0
    tokens: dict[str, int | str] = Field(default_factory=dict)
    raw: dict[str, object] = Field(default_factory=dict)
    error: str | None = None


class BenchmarkJudge(Protocol):
    def judge(self, *, question: NormalizedQuestion, answer: BackendAnswerResult) -> JudgeResult:
        ...


class DisabledJudge:
    def judge(self, *, question: NormalizedQuestion, answer: BackendAnswerResult) -> JudgeResult:
        return JudgeResult(ok=True, score=None, label="not_judged", raw={"question_id": question.question_id})


def estimate_text_tokens(text: str) -> int:
    return max(1, len(re.findall(r"\S+", text)))


def build_judge_user_prompt(*, question: NormalizedQuestion, answer: BackendAnswerResult) -> str:
    return JUDGE_USER_PROMPT.format(
        category=question.category or "unknown",
        question=question.question,
        gold_answer=question.gold_answer,
        answer=answer.answer,
    )


def parse_judge_json(raw_output: str) -> JudgeResult:
    payload = _load_json_object(raw_output)
    if payload is None:
        return JudgeResult(ok=False, label="judge_error", error_type="other", raw={"raw_output": raw_output}, error="invalid_json")
    score = payload.get("score")
    if score not in {0, 1, 0.0, 1.0}:
        return JudgeResult(ok=False, label="judge_error", error_type="other", raw={"raw_output": raw_output}, error="invalid_score")
    error_type = str(payload.get("error_type") or "none")
    if error_type not in JUDGE_ERROR_TYPES:
        error_type = "other"
    score_float = float(score)
    return JudgeResult(
        ok=True,
        score=score_float,
        label="correct" if score_float == 1.0 else "incorrect",
        explanation=str(payload.get("reason") or ""),
        error_type=error_type,
        raw={"raw_output": raw_output, "parsed": payload},
    )


class BinaryJudge:
    def __init__(
        self,
        *,
        model_name: str,
        generate: Callable[[str, str], str],
        repair_generate: Callable[[str, str], str] | None = None,
    ):
        self.model_name = model_name
        self.generate = generate
        self.repair_generate = repair_generate or generate

    def judge(self, *, question: NormalizedQuestion, answer: BackendAnswerResult) -> JudgeResult:
        started = monotonic()
        user_prompt = build_judge_user_prompt(question=question, answer=answer)
        try:
            raw_output = self.generate(JUDGE_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            return JudgeResult(
                ok=False,
                label="judge_error",
                error_type="other",
                latency_ms=(monotonic() - started) * 1000,
                raw={
                    "model": self.model_name,
                    "prompt_backend_blind": True,
                    "provider_error": str(exc),
                    "user_prompt": user_prompt,
                },
                error=str(exc),
            )
        result = parse_judge_json(raw_output)
        repaired = False
        if not result.ok:
            repair_prompt = JUDGE_REPAIR_PROMPT.format(raw_output=raw_output)
            repaired = True
            raw_repair = self.repair_generate(JUDGE_SYSTEM_PROMPT, repair_prompt)
            result = parse_judge_json(raw_repair)
            result.raw["repair_raw_output"] = raw_repair
        result.latency_ms = (monotonic() - started) * 1000
        result.tokens = {
            "judge_input_tokens": estimate_text_tokens(JUDGE_SYSTEM_PROMPT) + estimate_text_tokens(user_prompt),
            "judge_output_tokens": estimate_text_tokens(str(result.raw.get("raw_output") or raw_output)),
            "token_count_source": "estimated",
        }
        result.raw.update(
            {
                "model": self.model_name,
                "prompt_backend_blind": True,
                "repaired": repaired,
                "user_prompt": user_prompt,
            }
        )
        return result


class FixtureBinaryJudge(BinaryJudge):
    def __init__(self, *, model_name: str = "fixture-judge"):
        self._current_question: NormalizedQuestion | None = None
        self._current_answer: BackendAnswerResult | None = None
        super().__init__(model_name=model_name, generate=self._generate)

    def judge(self, *, question: NormalizedQuestion, answer: BackendAnswerResult) -> JudgeResult:
        self._current_question = question
        self._current_answer = answer
        try:
            return super().judge(question=question, answer=answer)
        finally:
            self._current_question = None
            self._current_answer = None

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        question = self._current_question
        answer = self._current_answer
        if question is None or answer is None:
            return json.dumps({"score": 0, "reason": "fixture state missing", "error_type": "other"})
        locomo_category = str(question.category or "").casefold()
        answer_text = answer.answer.casefold()
        if locomo_category in {"adversarial", "5"}:
            refused = bool(answer.refused) or any(
                phrase in answer_text
                for phrase in ("not supported", "don't have", "do not have", "unsupported", "cannot confirm")
            )
            return json.dumps(
                {
                    "score": 1 if refused else 0,
                    "reason": "false-premise answer refused" if refused else "false premise accepted",
                    "error_type": "none" if refused else "accepted_false_premise",
                }
            )
        expected = fake_answer(question=question.question, context=question.gold_answer)
        if question.gold_answer.casefold() in answer_text or expected.casefold() in answer_text:
            return json.dumps({"score": 1, "reason": "answer contains the gold fact", "error_type": "none"})
        if bool(answer.refused):
            return json.dumps({"score": 0, "reason": "supported question refused", "error_type": "missing_fact"})
        return json.dumps({"score": 0, "reason": "answer misses the gold fact", "error_type": "missing_fact"})


def _load_json_object(raw_output: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_output, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None

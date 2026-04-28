from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from typing import Any

from memco.benchmarks.backends.common import AnswerFn
from memco.benchmarks.judge import BinaryJudge
from memco.benchmarks.prompts import ANSWER_SYSTEM_PROMPT, ANSWER_USER_PROMPT
from memco.config import Settings, load_settings
from memco.llm import LLMProvider, build_llm_provider


FIXTURE_ANSWER_MODELS = {"", "fixture"}
FIXTURE_JUDGE_MODELS = {"", "none", "fixture", "fixture-judge"}
FIXTURE_EMBEDDING_MODELS = {"", "fixture", "fixture-embedding"}


def is_fixture_answer_model(model_name: str) -> bool:
    return model_name.strip().lower() in FIXTURE_ANSWER_MODELS


def is_fixture_judge_model(model_name: str) -> bool:
    return model_name.strip().lower() in FIXTURE_JUDGE_MODELS


def is_fixture_embedding_model(model_name: str) -> bool:
    return model_name.strip().lower() in FIXTURE_EMBEDDING_MODELS


def benchmark_llm_settings(*, project_root, model_name: str) -> Settings:
    settings = load_settings(project_root)
    settings.llm.model = model_name
    return settings


def build_text_provider(settings: Settings) -> LLMProvider:
    return build_llm_provider(settings)


def make_llm_answer_fn(provider: LLMProvider) -> AnswerFn:
    def answer(question: str, context: str) -> str:
        response = provider.complete_text(
            system_prompt=ANSWER_SYSTEM_PROMPT,
            prompt=ANSWER_USER_PROMPT.format(
                target_speaker_name="unknown",
                question=question,
                context=context,
            ),
            metadata={"operation": "benchmark_answer"},
        )
        return response.text.strip()

    return answer


def make_llm_judge(*, provider: LLMProvider, model_name: str) -> BinaryJudge:
    def generate(system_prompt: str, user_prompt: str) -> str:
        return provider.complete_text(
            system_prompt=system_prompt,
            prompt=user_prompt,
            metadata={"operation": "benchmark_judge"},
        ).text

    return BinaryJudge(model_name=model_name, generate=generate)


def make_openai_compatible_embed_fn(*, settings: Settings, model_name: str) -> Callable[[str], list[float]]:
    if settings.llm.provider not in {"openai", "openai-compatible", "openai_compatible"}:
        raise ValueError("Live benchmark embeddings require the openai-compatible provider")
    base_url = (os.environ.get("MEMCO_EMBEDDING_BASE_URL") or settings.llm.base_url).rstrip("/")
    api_key = os.environ.get("MEMCO_EMBEDDING_API_KEY") or settings.llm.api_key
    if not base_url or not api_key:
        raise ValueError(
            "Live benchmark embeddings require llm.base_url and llm.api_key "
            "or MEMCO_EMBEDDING_BASE_URL and MEMCO_EMBEDDING_API_KEY"
        )


    def embed(text: str) -> list[float]:
        payload: dict[str, Any] = {"model": model_name, "input": text}
        request = urllib.request.Request(
            url=f"{base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=getattr(settings.llm, "request_timeout_seconds", 60)) as response:
            body = json.loads(response.read().decode("utf-8"))
        embedding = body["data"][0]["embedding"]
        if not isinstance(embedding, list):
            raise ValueError("Embedding provider returned an invalid embedding")
        return [float(item) for item in embedding]

    return embed

from __future__ import annotations

import json
import math
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


@dataclass(frozen=True)
class LLMJSONResponse:
    content: Any
    raw_text: str
    usage: LLMUsage
    provider: str
    model: str


@dataclass(frozen=True)
class LLMTextResponse:
    text: str
    usage: LLMUsage
    provider: str
    model: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMJSONResponse: ...

    def complete_text(
        self,
        *,
        system_prompt: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMTextResponse: ...

    def count_tokens(self, *, text: str) -> int: ...

    def estimate_cost(self, *, input_tokens: int, output_tokens: int) -> float | None: ...


class MockLLMProvider:
    name = "mock"

    def __init__(
        self,
        *,
        model: str = "fixture",
        json_handler: Callable[..., Any] | None = None,
        text_handler: Callable[..., str] | None = None,
    ) -> None:
        self.model = model
        self._json_handler = json_handler
        self._text_handler = text_handler

    def count_tokens(self, *, text: str) -> int:
        cleaned = text.strip()
        if not cleaned:
            return 0
        return len(cleaned.split())

    def estimate_cost(self, *, input_tokens: int, output_tokens: int) -> float | None:
        return 0.0

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMJSONResponse:
        if self._json_handler is None:
            raise ValueError("MockLLMProvider requires a json_handler for complete_json")
        content = self._json_handler(
            system_prompt=system_prompt,
            prompt=prompt,
            schema_name=schema_name,
            metadata=metadata or {},
        )
        raw_text = json.dumps(content, ensure_ascii=False)
        input_tokens = self.count_tokens(text=system_prompt) + self.count_tokens(text=prompt)
        output_tokens = self.count_tokens(text=raw_text)
        return LLMJSONResponse(
            content=content,
            raw_text=raw_text,
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=self.estimate_cost(input_tokens=input_tokens, output_tokens=output_tokens),
            ),
            provider=self.name,
            model=self.model,
        )

    def complete_text(
        self,
        *,
        system_prompt: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMTextResponse:
        if self._text_handler is None:
            raise ValueError("MockLLMProvider requires a text_handler for complete_text")
        text = self._text_handler(system_prompt=system_prompt, prompt=prompt, metadata=metadata or {})
        input_tokens = self.count_tokens(text=system_prompt) + self.count_tokens(text=prompt)
        output_tokens = self.count_tokens(text=text)
        return LLMTextResponse(
            text=text,
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=self.estimate_cost(input_tokens=input_tokens, output_tokens=output_tokens),
            ),
            provider=self.name,
            model=self.model,
        )


class OpenAICompatibleLLMProvider:
    name = "openai-compatible"

    def __init__(self, *, model: str, base_url: str, api_key: str) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def count_tokens(self, *, text: str) -> int:
        cleaned = text.strip()
        if not cleaned:
            return 0
        return max(1, math.ceil(len(cleaned) / 4))

    def estimate_cost(self, *, input_tokens: int, output_tokens: int) -> float | None:
        return None

    def _post_json(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("MEMCO_LLM_API_KEY is required for the openai-compatible provider")
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def _usage_from_response(self, *, response: dict[str, Any], prompt_text: str, output_text: str) -> LLMUsage:
        usage = response.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", self.count_tokens(text=prompt_text)))
        output_tokens = int(usage.get("completion_tokens", self.count_tokens(text=output_text)))
        return LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=self.estimate_cost(input_tokens=input_tokens, output_tokens=output_tokens),
        )

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMJSONResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        response = self._post_json(payload=payload)
        raw_text = response["choices"][0]["message"]["content"]
        return LLMJSONResponse(
            content=json.loads(raw_text),
            raw_text=raw_text,
            usage=self._usage_from_response(response=response, prompt_text=f"{system_prompt}\n{prompt}", output_text=raw_text),
            provider=self.name,
            model=self.model,
        )

    def complete_text(
        self,
        *,
        system_prompt: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMTextResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        response = self._post_json(payload=payload)
        text = response["choices"][0]["message"]["content"]
        return LLMTextResponse(
            text=text,
            usage=self._usage_from_response(response=response, prompt_text=f"{system_prompt}\n{prompt}", output_text=text),
            provider=self.name,
            model=self.model,
        )


def build_llm_provider(
    settings,
    *,
    json_handler: Callable[..., Any] | None = None,
    text_handler: Callable[..., str] | None = None,
) -> LLMProvider:
    provider = settings.llm.provider.strip().lower()
    if provider == "mock":
        return MockLLMProvider(
            model=settings.llm.model,
            json_handler=json_handler,
            text_handler=text_handler,
        )
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        return OpenAICompatibleLLMProvider(
            model=settings.llm.model,
            base_url=settings.llm.base_url,
            api_key=settings.llm.api_key,
        )
    raise ValueError(f"Unsupported LLM provider: {settings.llm.provider}")

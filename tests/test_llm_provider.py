from __future__ import annotations

import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from memco.config import Settings
from memco.db import get_connection
from memco.llm import MockLLMProvider, OpenAICompatibleLLMProvider, build_llm_provider
from memco.repositories.fact_repository import FactRepository
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.runtime import ensure_runtime


class _OpenAICompatibleHandler(BaseHTTPRequestHandler):
    response_body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "items": [
                                {
                                    "domain": "biography",
                                    "category": "residence",
                                    "subcategory": "",
                                    "canonical_key": "alice:biography:residence:lisbon",
                                    "payload": {"city": "Lisbon"},
                                    "summary": "Alice lives in Lisbon.",
                                    "confidence": 0.9,
                                    "reason": "",
                                    "needs_review": False,
                                    "evidence": [
                                        {
                                            "quote": "I moved to Lisbon.",
                                            "message_ids": [],
                                            "source_segment_ids": [],
                                            "chunk_kind": "conversation",
                                        }
                                    ],
                                }
                            ]
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        body = json.dumps(self.response_body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def test_mock_llm_provider_returns_json_and_usage():
    provider = MockLLMProvider(
        model="fixture-x",
        json_handler=lambda **kwargs: [{"ok": True, "prompt": kwargs["prompt"]}],
    )

    result = provider.complete_json(
        system_prompt="Return JSON",
        prompt="payload",
        schema_name="fixture",
        metadata={"foo": "bar"},
    )

    assert result.provider == "mock"
    assert result.model == "fixture-x"
    assert result.content == [{"ok": True, "prompt": "payload"}]
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.usage.estimated_cost_usd == 0.0


def test_openai_compatible_provider_parses_response():
    provider = OpenAICompatibleLLMProvider(
        model="gpt-test",
        base_url="https://example.com/v1",
        api_key="secret",
    )
    provider._post_json = lambda **kwargs: {  # type: ignore[method-assign]
        "choices": [{"message": {"content": json.dumps({"items": [{"city": "Lisbon"}]})}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    }

    result = provider.complete_json(
        system_prompt="Return JSON",
        prompt="Extract city",
        schema_name="memory_fact_candidates",
    )

    assert result.provider == "openai-compatible"
    assert result.model == "gpt-test"
    assert result.content == {"items": [{"city": "Lisbon"}]}
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5
    assert result.usage.estimated_cost_usd is None


def test_extraction_service_from_settings_uses_configured_mock_provider():
    settings = Settings(root=Path("/tmp/memco-test-llm"))
    settings.llm.provider = "mock"
    settings.llm.model = "fixture-z"

    service = ExtractionService.from_settings(settings)
    candidates = service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")

    assert service.llm_provider.model == "fixture-z"
    assert candidates[0]["domain"] == "biography"
    assert candidates[0]["payload"]["city"] == "Lisbon"


def test_extraction_service_from_settings_uses_configured_openai_compatible_provider(monkeypatch):
    settings = Settings(root=Path("/tmp/memco-test-openai-provider"))
    settings.llm.provider = "openai-compatible"
    settings.llm.model = "gpt-test"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = "secret"

    service = ExtractionService.from_settings(settings)
    assert service.llm_provider.name == "openai-compatible"
    assert service.llm_provider.model == "gpt-test"

    service.llm_provider._post_json = lambda **kwargs: {  # type: ignore[method-assign]
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "items": [
                                {
                                    "domain": "biography",
                                    "category": "residence",
                                    "subcategory": "",
                                    "canonical_key": "alice:biography:residence:lisbon",
                                    "payload": {"city": "Lisbon"},
                                    "summary": "Alice lives in Lisbon.",
                                    "confidence": 0.9,
                                    "reason": "",
                                    "needs_review": False,
                                    "evidence": [
                                        {
                                            "quote": "I moved to Lisbon.",
                                            "message_ids": [],
                                            "source_segment_ids": [],
                                            "chunk_kind": "conversation",
                                        }
                                    ],
                                }
                            ]
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }

    candidates = service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")

    assert candidates[0]["domain"] == "biography"
    assert candidates[0]["payload"]["city"] == "Lisbon"
    summary = service.usage_tracker.summary()
    assert summary["llm_usage"]["operation_count"] == 1
    assert summary["llm_usage"]["input_tokens"] == 11
    assert summary["llm_usage"]["output_tokens"] == 7
    assert summary["deterministic_usage"]["operation_count"] == 0


def test_extraction_service_openai_compatible_live_http_path():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAICompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(root=Path("/tmp/memco-test-openai-live"))
        settings.llm.provider = "openai-compatible"
        settings.llm.model = "gpt-test"
        settings.llm.base_url = f"http://127.0.0.1:{server.server_port}/v1"
        settings.llm.api_key = "secret"

        service = ExtractionService.from_settings(settings)
        candidates = service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")

        assert candidates[0]["domain"] == "biography"
        assert candidates[0]["payload"]["city"] == "Lisbon"
        summary = service.usage_tracker.summary()
        assert summary["llm_usage"]["operation_count"] == 1
        assert summary["llm_usage"]["input_tokens"] == 11
        assert summary["llm_usage"]["output_tokens"] == 7
        assert summary["deterministic_usage"]["operation_count"] == 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_build_llm_provider_supports_openai_compatible_alias():
    settings = Settings(root=Path("/tmp/memco-test-provider"))
    settings.llm.provider = "openai_compatible"
    settings.llm.model = "gpt-4o-mini"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = "secret"

    provider = build_llm_provider(settings)

    assert provider.name == "openai-compatible"
    assert provider.model == "gpt-4o-mini"


def test_extraction_service_logs_token_usage_file(tmp_path):
    settings = ensure_runtime(Settings(root=tmp_path / "project"))
    source = tmp_path / "conversation.json"
    source.write_text(
        json.dumps(
            {"messages": [{"speaker": "Alice", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with get_connection(settings.db_path) as conn:
        FactRepository().upsert_person(
            conn,
            workspace_slug="default",
            display_name="Alice",
            slug="alice",
            person_type="human",
            aliases=["Alice"],
        )
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        extraction = ExtractionService.from_settings(settings)
        extraction.extract_candidates_from_conversation(conn, conversation_id=conversation.conversation_id)

    usage_log = settings.root / "var" / "log" / "llm_usage.jsonl"
    lines = usage_log.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["provider"] == "mock"
    assert payload["operation"] == "complete_json"
    assert payload["input_tokens"] > 0
    assert payload["output_tokens"] > 0
    assert payload["deterministic"] is True
    assert "Lisbon" not in json.dumps(payload)

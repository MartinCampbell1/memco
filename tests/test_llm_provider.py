from __future__ import annotations

import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from memco.config import Settings
from memco.config import load_settings
from memco.db import get_connection
from memco.llm import MockLLMProvider, OpenAICompatibleLLMProvider, build_llm_provider, llm_runtime_policy
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


class _DynamicOpenAICompatibleHandler(BaseHTTPRequestHandler):
    last_payload: dict | None = None

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_request = self.rfile.read(content_length)
        request_payload = json.loads(raw_request.decode("utf-8"))
        prompt_payload = json.loads(request_payload["messages"][1]["content"])
        text = prompt_payload["text"]
        self.__class__.last_payload = prompt_payload

        if text == "I don't like sushi because it feels too heavy.":
            items = [
                {
                    "domain": "preferences",
                    "category": "preference",
                    "subcategory": "",
                    "canonical_key": "alice:preferences:preference:sushi",
                    "payload": {
                        "value": "sushi",
                        "polarity": "dislike",
                        "strength": "medium",
                        "reason": "it feels too heavy",
                        "is_current": True,
                    },
                    "summary": "Alice dislikes sushi.",
                    "confidence": 0.9,
                    "reason": "",
                    "needs_review": False,
                    "evidence": [
                        {
                            "quote": "I don't like sushi because it feels too heavy.",
                            "message_ids": [],
                            "source_segment_ids": [],
                            "chunk_kind": "conversation",
                        }
                    ],
                }
            ]
        elif text == "Tea is my go-to drink when I need to focus.":
            items = [
                {
                    "domain": "preferences",
                    "category": "preference",
                    "subcategory": "",
                    "canonical_key": "alice:preferences:preference:tea",
                    "payload": {
                        "value": "Tea",
                        "polarity": "like",
                        "strength": "medium",
                        "reason": "",
                        "is_current": True,
                    },
                    "summary": "Alice likes Tea.",
                    "confidence": 0.84,
                    "reason": "",
                    "needs_review": False,
                    "evidence": [
                        {
                            "quote": "Tea is my go-to drink when I need to focus.",
                            "message_ids": [],
                            "source_segment_ids": [],
                            "chunk_kind": "conversation",
                        }
                    ],
                }
            ]
        elif text == "Lisbon is my base these days.":
            items = [
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
                            "quote": "Lisbon is my base these days.",
                            "message_ids": [],
                            "source_segment_ids": [],
                            "chunk_kind": "conversation",
                        }
                    ],
                }
            ]
        elif text == "I might move to Berlin next year.":
            items = []
        elif text == "I attended PyCon around 2024 with Bob and it was great.":
            items = [
                {
                    "domain": "experiences",
                    "category": "event",
                    "subcategory": "",
                    "canonical_key": "alice:experiences:event:pycon",
                    "payload": {
                        "event": "PyCon",
                        "summary": "I attended PyCon around 2024 with Bob and it was great.",
                        "participants": ["Bob"],
                        "event_at": "",
                        "temporal_anchor": "around 2024",
                        "outcome": "",
                        "valence": "positive",
                    },
                    "summary": "Alice experienced PyCon.",
                    "confidence": 0.88,
                    "reason": "",
                    "needs_review": False,
                    "evidence": [
                        {
                            "quote": "I attended PyCon around 2024 with Bob and it was great.",
                            "message_ids": [],
                            "source_segment_ids": [],
                            "chunk_kind": "conversation",
                        }
                    ],
                }
            ]
        elif text == "Я предпочитаю tea.":
            items = [
                {
                    "domain": "preferences",
                    "category": "preference",
                    "subcategory": "",
                    "canonical_key": "alice:preferences:preference:tea",
                    "payload": {
                        "value": "tea",
                        "polarity": "like",
                        "strength": "medium",
                        "reason": "",
                        "is_current": True,
                    },
                    "summary": "Alice likes tea.",
                    "confidence": 0.83,
                    "reason": "",
                    "needs_review": False,
                    "evidence": [
                        {
                            "quote": "Я предпочитаю tea.",
                            "message_ids": [],
                            "source_segment_ids": [],
                            "chunk_kind": "conversation",
                        }
                    ],
                }
            ]
        elif text == "I moved to Lisbon but I have no proof.":
            items = [
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
                    "evidence": [],
                }
            ]
        else:  # pragma: no cover
            items = []

        response_body = {
            "choices": [{"message": {"content": json.dumps({"items": items}, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 9},
        }
        body = json.dumps(response_body).encode("utf-8")
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


def test_openai_compatible_provider_uses_request_timeout(monkeypatch):
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": json.dumps({"items": []})}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("memco.llm.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleLLMProvider(
        model="gpt-test",
        base_url="https://example.com/v1",
        api_key="secret",
    )

    provider.complete_json(
        system_prompt="Return JSON",
        prompt="Extract city",
        schema_name="memory_fact_candidates",
    )

    assert captured["timeout"] == 60


def test_extraction_service_from_settings_uses_configured_mock_provider():
    settings = Settings(root=Path("/tmp/memco-test-llm"))
    settings.runtime.profile = "fixture"
    settings.llm.provider = "mock"
    settings.llm.model = "fixture-z"
    settings.llm.allow_mock_provider = True

    service = ExtractionService.from_settings(settings)
    candidates = service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")

    assert service.llm_provider.model == "fixture-z"
    assert candidates[0]["domain"] == "biography"
    assert candidates[0]["payload"]["city"] == "Lisbon"


def test_extraction_service_mock_provider_combined_legacy_mode_preserves_combined_output(tmp_path):
    settings = Settings(root=tmp_path / "mock-combined-legacy")
    settings.runtime.profile = "fixture"
    settings.llm.provider = "mock"
    settings.llm.allow_mock_provider = True
    settings.extraction.mode = "combined_legacy"

    service = ExtractionService.from_settings(settings)
    candidates = service.extract_candidates(
        source_text="I moved to Lisbon. I prefer coffee. I use Python.",
        person_hint="Alice",
    )

    domains = {candidate["domain"] for candidate in candidates}
    assert {"biography", "preferences", "work"} <= domains
    summary = service.usage_tracker.summary()
    assert summary["deterministic_usage"]["operation_count"] == 1
    assert summary["production_accounting"]["by_domain"]["combined_legacy"]["operation_count"] == 1


def test_extraction_service_from_settings_defaults_to_openai_compatible_runtime():
    settings = Settings(root=Path("/tmp/memco-test-runtime-default"))

    service = ExtractionService.from_settings(settings)

    assert service.llm_provider.name == "openai-compatible"


def test_llm_runtime_policy_requires_credentials_for_openai_compatible_provider():
    settings = Settings(root=Path("/tmp/memco-test-runtime-policy-missing-key"))

    policy = llm_runtime_policy(settings)

    assert policy["provider"] == "openai-compatible"
    assert policy["runtime_profile"] == "repo-local"
    assert policy["base_url_present"] is True
    assert policy["credentials_present"] is False
    assert policy["provider_configured"] is False
    assert policy["fixture_only"] is False
    assert policy["release_eligible"] is False
    assert "api_key" in policy["reason"]


def test_llm_runtime_policy_marks_callable_openai_compatible_runtime_release_eligible():
    settings = Settings(root=Path("/tmp/memco-test-runtime-policy-live"))
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = "secret"

    policy = llm_runtime_policy(settings)

    assert policy["provider"] == "openai-compatible"
    assert policy["base_url_present"] is True
    assert policy["credentials_present"] is True
    assert policy["provider_configured"] is True
    assert policy["fixture_only"] is False
    assert policy["release_eligible"] is True


def test_extraction_service_rejects_mock_config_without_explicit_opt_in(tmp_path):
    root = tmp_path / "project"
    (root / "var" / "config").mkdir(parents=True, exist_ok=True)
    (root / "var" / "config" / "settings.yaml").write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "  model: fixture-legacy",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    settings = load_settings(root)
    assert settings.llm.allow_mock_provider is False

    with pytest.raises(ValueError, match="fixture/test-only"):
        ExtractionService.from_settings(settings)


def test_extraction_service_supports_explicit_fixture_mock_config_file(tmp_path):
    root = tmp_path / "project"
    (root / "var" / "config").mkdir(parents=True, exist_ok=True)
    (root / "var" / "config" / "settings.yaml").write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "  model: fixture-legacy",
                "  allow_mock_provider: true",
                "runtime:",
                "  profile: fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    settings = load_settings(root)
    service = ExtractionService.from_settings(settings)
    candidates = service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")

    assert service.llm_provider.name == "mock"
    assert settings.llm.allow_mock_provider is True
    assert settings.runtime.profile == "fixture"
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
    assert summary["llm_usage"]["operation_count"] == 5
    assert summary["llm_usage"]["input_tokens"] == 55
    assert summary["llm_usage"]["output_tokens"] == 35
    assert summary["deterministic_usage"]["operation_count"] == 0


def test_extraction_service_rejects_malformed_provider_candidates():
    settings = Settings(root=Path("/tmp/memco-test-openai-invalid"))
    settings.llm.provider = "openai-compatible"
    settings.llm.model = "gpt-test"
    settings.llm.base_url = "https://router.example/v1"
    settings.llm.api_key = "secret"

    service = ExtractionService.from_settings(settings)
    service.llm_provider._post_json = lambda **kwargs: {  # type: ignore[method-assign]
        "choices": [{"message": {"content": json.dumps({"items": [{"domain": "biography"}]})}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }

    try:
        service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")
    except ValueError as exc:
        assert "candidate is missing required keys" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected malformed provider candidate to be rejected")


def test_extraction_service_normalizes_string_evidence_from_provider():
    provider = MockLLMProvider(
        model="fixture-x",
        json_handler=lambda **kwargs: {
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
                    "evidence": "I moved to Lisbon.",
                }
            ]
        },
    )

    service = ExtractionService(llm_provider=provider)
    candidates = service.extract_candidates(source_text="I moved to Lisbon.", person_hint="Alice")

    assert candidates[0]["payload"]["city"] == "Lisbon"
    assert candidates[0]["evidence"][0]["quote"] == "I moved to Lisbon."
    assert candidates[0]["evidence"][0]["chunk_kind"] == "conversation"


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
        assert summary["llm_usage"]["operation_count"] == 5
        assert summary["llm_usage"]["input_tokens"] == 55
        assert summary["llm_usage"]["output_tokens"] == 35
        assert summary["deterministic_usage"]["operation_count"] == 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "I don't like sushi because it feels too heavy.",
            ("preferences", "preference", {"value": "sushi", "polarity": "dislike", "is_current": True}),
        ),
        (
            "Tea is my go-to drink when I need to focus.",
            ("preferences", "preference", {"value": "Tea", "polarity": "like", "is_current": True}),
        ),
        (
            "Lisbon is my base these days.",
            ("biography", "residence", {"city": "Lisbon"}),
        ),
        (
            "I attended PyCon around 2024 with Bob and it was great.",
            ("experiences", "event", {"event": "PyCon", "event_at": "", "temporal_anchor": "around 2024"}),
        ),
        (
            "Я предпочитаю tea.",
            ("preferences", "preference", {"value": "tea", "polarity": "like"}),
        ),
    ],
)
def test_extraction_service_openai_compatible_provider_path_covers_llm_first_regressions(text, expected):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DynamicOpenAICompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(root=Path("/tmp/memco-test-openai-regressions"))
        settings.runtime.profile = "repo-local"
        settings.llm.provider = "openai-compatible"
        settings.llm.model = "gpt-test"
        settings.llm.base_url = f"http://127.0.0.1:{server.server_port}/v1"
        settings.llm.api_key = "secret"

        service = ExtractionService.from_settings(settings)
        candidates = service.extract_candidates(source_text=text, person_hint="Alice")

        assert _DynamicOpenAICompatibleHandler.last_payload is not None
        assert _DynamicOpenAICompatibleHandler.last_payload["extraction_mode"] == "llm_first_structured_extraction"
        assert "output_contract" in _DynamicOpenAICompatibleHandler.last_payload
        assert candidates
        domain, category, payload_expectations = expected
        assert candidates[0]["domain"] == domain
        assert candidates[0]["category"] == category
        for key, value in payload_expectations.items():
            assert candidates[0]["payload"][key] == value
        summary = service.usage_tracker.summary()
        assert summary["llm_usage"]["operation_count"] == 5
        assert summary["deterministic_usage"]["operation_count"] == 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_extraction_service_openai_compatible_provider_path_can_skip_hypothetical_candidate():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DynamicOpenAICompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(root=Path("/tmp/memco-test-openai-hypothetical"))
        settings.runtime.profile = "repo-local"
        settings.llm.provider = "openai-compatible"
        settings.llm.model = "gpt-test"
        settings.llm.base_url = f"http://127.0.0.1:{server.server_port}/v1"
        settings.llm.api_key = "secret"

        service = ExtractionService.from_settings(settings)
        candidates = service.extract_candidates(source_text="I might move to Berlin next year.", person_hint="Alice")

        assert candidates == []
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_extraction_service_rejects_provider_candidates_without_evidence():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DynamicOpenAICompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(root=Path("/tmp/memco-test-openai-no-evidence"))
        settings.runtime.profile = "repo-local"
        settings.llm.provider = "openai-compatible"
        settings.llm.model = "gpt-test"
        settings.llm.base_url = f"http://127.0.0.1:{server.server_port}/v1"
        settings.llm.api_key = "secret"

        service = ExtractionService.from_settings(settings)

        with pytest.raises(ValueError, match="candidate evidence must be non-empty"):
            service.extract_candidates(source_text="I moved to Lisbon but I have no proof.", person_hint="Alice")
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


def test_build_llm_provider_rejects_mock_without_fixture_opt_in():
    settings = Settings(root=Path("/tmp/memco-test-provider"))
    settings.llm.provider = "mock"
    settings.llm.model = "fixture"
    settings.llm.allow_mock_provider = False

    with pytest.raises(ValueError, match="fixture/test-only"):
        build_llm_provider(settings)


def test_extraction_service_logs_token_usage_file(tmp_path):
    settings = Settings(root=tmp_path / "project")
    settings.runtime.profile = "fixture"
    settings.storage.engine = "sqlite"
    settings.llm.provider = "mock"
    settings.llm.model = "fixture"
    settings.llm.allow_mock_provider = True
    settings = ensure_runtime(settings)
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

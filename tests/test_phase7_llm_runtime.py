from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from memco.config import Settings
from memco.models.retrieval import RetrievalHit, RetrievalRequest, RetrievalResult
from memco.services.chat_runtime import build_chat_services


class _Phase7OpenAICompatibleHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        request_payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        self.__class__.requests.append(request_payload)
        user_prompt = request_payload["messages"][1]["content"]
        if "Plan memory retrieval" in user_prompt:
            content = {
                "target_person": "alice",
                "domains": [
                    {"domain": "biography", "categories": ["residence"], "field_query": "Where does Alice live?", "reason": "residence"},
                    {"domain": "work", "categories": ["employment"], "field_query": "Where does Alice work?", "reason": "work"},
                ],
                "claim_checks": [{"type": "location", "value": "Lisbon", "must_be_supported": True}],
                "temporal_mode": "current",
                "false_premise_risk": "high",
                "requires_temporal_reasoning": False,
                "requires_cross_domain_synthesis": True,
                "must_not_answer_without_evidence": True,
                "question_type": "multi_hop",
            }
        elif "Synthesize an evidence-bound answer" in user_prompt:
            content = {
                "answer": "Alice lives in Lisbon.",
                "support_level": "supported",
                "unsupported_claims": [],
                "answerable": True,
                "refused": False,
                "used_fact_ids": [1],
                "used_evidence_ids": [21],
            }
        else:  # pragma: no cover - defensive
            content = {"error": "unexpected prompt"}
        response = {
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 7},
        }
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def test_phase7_chat_services_use_configured_local_openai_compatible_provider(tmp_path):
    _Phase7OpenAICompatibleHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Phase7OpenAICompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(root=tmp_path)
        settings.llm.provider = "openai-compatible"
        settings.llm.model = "phase7-local"
        settings.llm.base_url = f"http://127.0.0.1:{server.server_port}/v1"
        settings.llm.api_key = "local-test-key"
        retrieval_service, answer_service = build_chat_services(settings)

        plan = retrieval_service.planner_service.plan(
            RetrievalRequest(
                workspace="default",
                person_slug="alice",
                query="Where does Alice live and work?",
            )
        )
        answer = answer_service.build_answer(
            query="Where does Alice live?",
            retrieval_result=RetrievalResult(
                query="Where does Alice live?",
                unsupported_premise_detected=False,
                support_level="supported",
                hits=[
                    RetrievalHit(
                        fact_id=1,
                        domain="biography",
                        category="residence",
                        summary="Alice lives in Lisbon.",
                        confidence=0.9,
                        score=2.0,
                        payload={"city": "Lisbon"},
                        evidence=[{"evidence_id": 21, "quote_text": "Alice lives in Lisbon."}],
                    )
                ],
            ),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert plan.plan_version == "v2_llm"
    assert {(item.domain, item.category) for item in plan.domain_queries} == {("biography", "residence"), ("work", "employment")}
    assert answer["refused"] is False
    assert answer["answer"] == "Alice lives in Lisbon."
    assert answer["used_fact_ids"] == [1]
    assert answer["used_evidence_ids"] == [21]
    assert len(_Phase7OpenAICompatibleHandler.requests) == 2


def test_phase7_chat_services_keep_deterministic_path_without_live_provider(tmp_path):
    settings = Settings(root=tmp_path)
    retrieval_service, answer_service = build_chat_services(settings)

    plan = retrieval_service.planner_service.plan(
        RetrievalRequest(
            workspace="default",
            person_slug="alice",
            query="Where does Alice live?",
        )
    )
    answer = answer_service.build_answer(
        query="Where does Alice live?",
        retrieval_result=RetrievalResult(
            query="Where does Alice live?",
            unsupported_premise_detected=False,
            support_level="supported",
            hits=[
                RetrievalHit(
                    fact_id=1,
                    domain="biography",
                    category="residence",
                    summary="Alice lives in Lisbon.",
                    confidence=0.9,
                    score=2.0,
                    payload={"city": "Lisbon"},
                    evidence=[{"evidence_id": 21}],
                )
            ],
        ),
    )

    assert plan.plan_version == "v2"
    assert answer["answer"] == "Alice lives in Lisbon."

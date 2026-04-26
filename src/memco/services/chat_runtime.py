from __future__ import annotations

import os

from memco.llm import build_llm_provider, llm_runtime_policy
from memco.llm_usage import LLMUsageTracker
from memco.services.answer_service import AnswerService
from memco.services.planner_service import PlannerService
from memco.services.retrieval_service import RetrievalService


def _planner_llm_mode() -> str:
    mode = os.environ.get("MEMCO_LLM_PLANNER_MODE", "").strip().lower()
    if mode in {"always", "hybrid", "off"}:
        return mode
    return "hybrid"


def build_chat_services(settings, *, usage_tracker: LLMUsageTracker | None = None) -> tuple[RetrievalService, AnswerService]:
    provider = None
    if llm_runtime_policy(settings)["release_eligible"]:
        provider = build_llm_provider(settings)
    planner = PlannerService(usage_tracker=usage_tracker, llm_provider=provider, llm_mode=_planner_llm_mode())
    retrieval_service = RetrievalService(planner_service=planner, usage_tracker=usage_tracker)
    answer_service = AnswerService(usage_tracker=usage_tracker, llm_provider=provider)
    return retrieval_service, answer_service

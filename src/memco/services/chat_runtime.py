from __future__ import annotations

from memco.llm import build_llm_provider, llm_runtime_policy
from memco.llm_usage import LLMUsageTracker
from memco.services.answer_service import AnswerService
from memco.services.planner_service import PlannerService
from memco.services.retrieval_service import RetrievalService


def build_chat_services(settings, *, usage_tracker: LLMUsageTracker | None = None) -> tuple[RetrievalService, AnswerService]:
    provider = None
    if llm_runtime_policy(settings)["release_eligible"]:
        provider = build_llm_provider(settings)
    planner = PlannerService(usage_tracker=usage_tracker, llm_provider=provider)
    retrieval_service = RetrievalService(planner_service=planner, usage_tracker=usage_tracker)
    answer_service = AnswerService(usage_tracker=usage_tracker, llm_provider=provider)
    return retrieval_service, answer_service

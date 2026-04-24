from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from memco.llm import LLMProvider
from memco.llm_usage import LLMUsageEvent, LLMUsageTracker, estimate_token_count
from memco.models.retrieval import DetailPolicy


class LLMAnswerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    support_level: str
    used_fact_ids: list[int] = Field(default_factory=list)
    used_evidence_ids: list[int] = Field(default_factory=list)


class AnswerService:
    NON_FACTUAL_DOMAINS = {"style", "psychometrics"}
    YES_NO_PREFIXES = {
        "do",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
        "can",
        "could",
        "will",
        "would",
        "has",
        "have",
        "had",
        "should",
    }

    def __init__(
        self,
        usage_tracker: LLMUsageTracker | None = None,
        llm_provider: LLMProvider | None = None,
        use_llm: bool | None = None,
        fail_closed_on_provider_error: bool = True,
    ) -> None:
        self.usage_tracker = usage_tracker
        self.llm_provider = llm_provider
        self.use_llm = bool(llm_provider) if use_llm is None else use_llm
        self.fail_closed_on_provider_error = fail_closed_on_provider_error

    def _temporal_value(self, hit) -> tuple[str, str]:
        event_at = str(getattr(hit, "event_at", "") or "").strip()
        if event_at:
            return "event_at", event_at
        valid_from = str(getattr(hit, "valid_from", "") or "").strip()
        if valid_from:
            return "valid_from", valid_from
        observed_at = str(getattr(hit, "observed_at", "") or "").strip()
        if observed_at:
            return "observed_at", observed_at
        return "unknown", ""

    def _answer_ids(self, retrieval_result) -> tuple[list[int], list[int]]:
        fact_ids: list[int] = []
        evidence_ids: list[int] = []
        for hit in retrieval_result.hits:
            fact_ids.append(int(hit.fact_id))
            for evidence in hit.evidence:
                evidence_id = evidence.get("evidence_id")
                if evidence_id is None:
                    continue
                evidence_ids.append(int(evidence_id))
        return fact_ids, evidence_ids

    def _present_hit(self, hit, *, detail_policy: DetailPolicy) -> dict:
        if detail_policy == "core_only":
            return {
                "fact_id": int(hit.fact_id),
                "domain": hit.domain,
                "category": hit.category,
                "summary": hit.summary,
            }
        return hit.model_dump(mode="json")

    def _is_yes_no_query(self, query: str) -> bool:
        first = query.strip().split(maxsplit=1)[0].lower().strip("¿?!.:,;") if query.strip() else ""
        return first in self.YES_NO_PREFIXES

    def _safe_known_facts(self, retrieval_result) -> list[str]:
        explicit = [str(item).strip() for item in getattr(retrieval_result, "safe_known_facts", []) if str(item).strip()]
        if explicit:
            return explicit
        facts: list[str] = []
        seen: set[str] = set()
        for hit in self._factual_hits(retrieval_result):
            summary = str(getattr(hit, "summary", "") or "").strip()
            if not summary or summary in seen:
                continue
            seen.add(summary)
            facts.append(summary)
        return facts

    def _answerable(self, *, query: str, refused: bool, retrieval_result) -> bool:
        if getattr(retrieval_result, "answerable", True) is False:
            return False
        support_level = getattr(retrieval_result, "support_level", "unsupported")
        unsupported_claims = list(getattr(retrieval_result, "unsupported_claims", []) or [])
        if support_level == "supported" and not refused:
            return True
        if support_level == "partial" and not refused:
            return not (self._is_yes_no_query(query) and bool(unsupported_claims))
        return False

    def _must_refuse_partial(self, *, query: str, retrieval_result) -> bool:
        if getattr(retrieval_result, "answerable", True) is False:
            return True
        return bool(getattr(retrieval_result, "unsupported_claims", []) or []) and self._is_yes_no_query(query)

    def _claim_details(self, unsupported_claims: list[str]) -> list[dict]:
        details: list[dict] = []
        prefixes = {
            "No evidence for employer claim:": "employer",
            "No evidence for location claim:": "location",
            "No evidence for preference claim:": "preference",
            "No evidence for event claim:": "event",
            "No evidence for date claim:": "date",
            "No evidence that this relationship claim is supported:": "relation",
            "No evidence for related person in the premise:": "relation_target",
            "No evidence for named entity in the premise:": "name",
        }
        for claim in unsupported_claims:
            claim_type = "claim"
            value = claim
            for prefix, mapped_type in prefixes.items():
                if claim.startswith(prefix):
                    claim_type = mapped_type
                    value = claim[len(prefix) :].strip().rstrip(".")
                    break
            details.append({"type": claim_type, "value": value, "reason": "no_supporting_fact", "text": claim})
        return details

    def _unsupported_values(self, unsupported_claims: list[str]) -> list[str]:
        return [item["value"] for item in self._claim_details(unsupported_claims) if item["value"]]

    def _confirmed_fact_details(self, retrieval_result) -> list[dict]:
        details: list[dict] = []
        for hit in self._factual_hits(retrieval_result):
            details.append(
                {
                    "fact_id": int(hit.fact_id),
                    "domain": hit.domain,
                    "category": hit.category,
                    "summary": hit.summary,
                    "confidence": hit.confidence,
                }
            )
        return details

    def _evidence_details(self, retrieval_result) -> list[dict]:
        details: list[dict] = []
        for hit in self._factual_hits(retrieval_result):
            for evidence in hit.evidence:
                item = dict(evidence)
                item["fact_id"] = int(hit.fact_id)
                item["domain"] = hit.domain
                item["category"] = hit.category
                details.append(item)
        return details

    def _false_premise_answer(self, *, query: str, retrieval_result, fallback: str) -> str:
        supported = " ".join(self._safe_known_facts(retrieval_result)).strip()
        values = self._unsupported_values(list(getattr(retrieval_result, "unsupported_claims", []) or []))
        match = re.match(
            r"\s*(?i:does)\s+(?P<subject>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*)*)\b.*?\b(?i:work)\s+(?i:at)\s+(?P<org>[^?.!,]+)",
            query,
        )
        if match:
            subject = " ".join(match.group("subject").split())
            org = values[0] if values else "that organization"
            answer = f"I do not have evidence that {subject} works at {org}."
        else:
            unsupported = values[0] if values else "that claim"
            answer = f"I do not have evidence for {unsupported} in this query."
        if supported:
            answer = f"{answer} Confirmed memory says {supported}"
        return answer or fallback

    def _payload(
        self,
        *,
        query: str,
        answer: str,
        refused: bool,
        retrieval_result,
        detail_policy: DetailPolicy,
        used_fact_ids: list[int] | None = None,
        used_evidence_ids: list[int] | None = None,
    ) -> dict:
        fact_ids, evidence_ids = self._answer_ids(retrieval_result)
        used_fact_ids = fact_ids if used_fact_ids is None else used_fact_ids
        used_evidence_ids = evidence_ids if used_evidence_ids is None else used_evidence_ids
        support_level = getattr(retrieval_result, "support_level", "unsupported")
        unsupported_claims = list(getattr(retrieval_result, "unsupported_claims", []) or [])
        answerable = self._answerable(query=query, refused=refused, retrieval_result=retrieval_result)
        safe_known_facts = self._safe_known_facts(retrieval_result)
        confirmed_fact_details = self._confirmed_fact_details(retrieval_result)
        evidence_details = self._evidence_details(retrieval_result)
        target_person = dict(getattr(retrieval_result, "target_person", {}) or {})
        refusal_category = getattr(retrieval_result, "refusal_category", "") or (
            "contradicted_by_memory"
            if support_level == "contradicted"
            else "unsupported_no_evidence"
            if support_level == "partial" and refused and self._is_yes_no_query(query)
            else "unsupported_no_evidence"
            if refused
            else ""
        )
        must_not_use_as_fact = bool(getattr(retrieval_result, "must_not_use_as_fact", False)) or refused or not answerable
        claim_details = self._claim_details(unsupported_claims)
        return {
            "answer": answer,
            "safe_response": answer,
            "answerable": answerable,
            "refused": refused,
            "support_level": support_level,
            "refusal_category": refusal_category,
            "must_not_use_as_fact": must_not_use_as_fact,
            "unsupported_claims": unsupported_claims,
            "unsupported_claim_details": claim_details,
            "safe_known_facts": safe_known_facts,
            "confirmed_facts": safe_known_facts,
            "detail_policy": detail_policy,
            "hits": [self._present_hit(hit, detail_policy=detail_policy) for hit in retrieval_result.hits],
            "fact_ids": fact_ids,
            "evidence_ids": evidence_ids,
            "used_fact_ids": used_fact_ids,
            "used_evidence_ids": used_evidence_ids,
            "agent_response": {
                "answerable": answerable,
                "query": getattr(retrieval_result, "query", query) or query,
                "target_person": target_person,
                "support_level": support_level,
                "safe_response": answer,
                "unsupported_claims": claim_details,
                "confirmed_facts": confirmed_fact_details,
                "safe_known_facts": safe_known_facts,
                "evidence": evidence_details,
                "fact_ids": fact_ids,
                "evidence_ids": evidence_ids,
                "used_fact_ids": used_fact_ids,
                "used_evidence_ids": used_evidence_ids,
                "must_not_use_as_fact": must_not_use_as_fact,
                "refusal_category": refusal_category,
            },
        }

    def _record_usage(self, *, query: str, retrieval_result, answer_payload: dict) -> None:
        if self.usage_tracker is None:
            return
        factual_hits = self._factual_hits(retrieval_result)
        input_text = " ".join(
            [
                query,
                " ".join(hit.summary for hit in factual_hits),
                " ".join(retrieval_result.unsupported_claims),
            ]
        )
        output_text = answer_payload["answer"]
        self.usage_tracker.record(
            LLMUsageEvent(
                provider="deterministic",
                model="rule-based-answer",
                operation="answer",
                input_tokens=estimate_token_count(input_text),
                output_tokens=estimate_token_count(output_text),
                estimated_cost_usd=0.0,
                deterministic=True,
                metadata={"stage": "answer"},
            )
        )

    def _factual_hits(self, retrieval_result):
        return [hit for hit in retrieval_result.hits if getattr(hit, "domain", "") not in self.NON_FACTUAL_DOMAINS]

    def _should_use_provider_answer(self, retrieval_result) -> bool:
        return bool(
            self.use_llm
            and self.llm_provider is not None
            and getattr(retrieval_result, "support_level", "unsupported") == "supported"
            and getattr(retrieval_result, "answerable", True) is not False
            and not getattr(retrieval_result, "unsupported_claims", [])
        )

    def _answer_prompt(self, *, query: str, retrieval_result, detail_policy: DetailPolicy) -> tuple[str, str]:
        facts = []
        for hit in self._factual_hits(retrieval_result):
            facts.append(
                {
                    "fact_id": int(hit.fact_id),
                    "domain": hit.domain,
                    "category": hit.category,
                    "summary": hit.summary,
                    "confidence": hit.confidence,
                    "payload": hit.payload,
                    "evidence": hit.evidence,
                    "observed_at": hit.observed_at,
                    "valid_from": hit.valid_from,
                    "valid_to": hit.valid_to,
                    "event_at": hit.event_at,
                }
            )
        system_prompt = (
            "You are Memco's answer synthesis component. Return only valid JSON. "
            "Answer strictly from the provided confirmed facts and evidence. "
            "Do not add, infer, or guess new personal facts. "
            "If the provided facts and evidence do not support the answer, refuse."
        )
        prompt = json.dumps(
            {
                "task": "Synthesize an evidence-bound answer for the user.",
                "query": query,
                "support_level": getattr(retrieval_result, "support_level", "unsupported"),
                "detail_policy": detail_policy,
                "confirmed_facts": facts,
                "output_schema": {
                    "answer": "string",
                    "support_level": "supported|partial|unsupported|ambiguous|contradicted",
                    "used_fact_ids": ["fact ids used by the answer"],
                    "used_evidence_ids": ["evidence ids used by the answer"],
                },
                "rules": [
                    "Use only confirmed_facts and their evidence.",
                    "Do not introduce facts that are absent from confirmed_facts.",
                    "Every supported answer must cite at least one used_fact_id and used_evidence_id.",
                    "Return JSON only.",
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return system_prompt, prompt

    def _record_provider_usage(self, *, response, answer_payload: dict) -> None:
        if self.usage_tracker is None:
            return
        self.usage_tracker.record(
            LLMUsageEvent(
                provider=response.provider,
                model=response.model,
                operation="answer",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                estimated_cost_usd=response.usage.estimated_cost_usd,
                deterministic=False,
                metadata={"stage": "answer", "support_level": answer_payload.get("support_level", "")},
            )
        )

    def _try_provider_answer(self, *, query: str, retrieval_result, detail_policy: DetailPolicy) -> dict | None:
        if self.llm_provider is None:
            return None
        try:
            system_prompt, prompt = self._answer_prompt(query=query, retrieval_result=retrieval_result, detail_policy=detail_policy)
            response = self.llm_provider.complete_json(
                system_prompt=system_prompt,
                prompt=prompt,
                schema_name="memco_evidence_bound_answer_v1",
                metadata={"operation": "answer"},
            )
            output = LLMAnswerOutput.model_validate(response.content)
            payload = self._payload_from_provider_output(
                output=output,
                query=query,
                retrieval_result=retrieval_result,
                detail_policy=detail_policy,
            )
            self._record_provider_usage(response=response, answer_payload=payload)
            return payload
        except Exception:
            return None

    def _grounding_allowed_text(self, *, retrieval_result) -> str:
        allowed_text_parts: list[str] = []
        for hit in self._factual_hits(retrieval_result):
            allowed_text_parts.extend(
                [
                    str(hit.summary or ""),
                    json.dumps(hit.payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(hit.evidence, ensure_ascii=False, sort_keys=True),
                ]
            )
        return " ".join(allowed_text_parts)

    def _unsupported_named_phrases_in_answer(self, *, answer: str, query: str, retrieval_result) -> list[str]:
        allowed_text = self._grounding_allowed_text(retrieval_result=retrieval_result).lower()
        allowed_sentence_words = {
            "I",
            "The",
            "This",
            "That",
            "These",
            "Those",
            "She",
            "He",
            "They",
            "According",
            "Confirmed",
            "Memory",
        }
        unsupported: list[str] = []
        seen: set[str] = set()
        for match in re.findall(r"\b[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*\b", answer):
            phrase = " ".join(match.split())
            if phrase in allowed_sentence_words:
                continue
            if phrase.lower() in allowed_text:
                continue
            if phrase.lower() in seen:
                continue
            seen.add(phrase.lower())
            unsupported.append(phrase)
        return unsupported

    def _unsupported_content_tokens_in_answer(self, *, answer: str, query: str, retrieval_result) -> list[str]:
        allowed_text = self._grounding_allowed_text(retrieval_result=retrieval_result).lower()
        allowed_tokens = set(re.findall(r"[a-z0-9][a-z0-9&\-]*", allowed_text))
        allowed_generic_tokens = {
            "a",
            "according",
            "an",
            "and",
            "are",
            "as",
            "at",
            "based",
            "be",
            "by",
            "can",
            "confirmed",
            "does",
            "evidence",
            "fact",
            "facts",
            "for",
            "from",
            "have",
            "he",
            "her",
            "his",
            "i",
            "in",
            "is",
            "it",
            "known",
            "memory",
            "on",
            "only",
            "provided",
            "s",
            "she",
            "that",
            "the",
            "their",
            "there",
            "they",
            "this",
            "to",
            "with",
        }
        unsupported: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[a-z0-9][a-z0-9&\-]*", answer.lower()):
            if len(token) <= 1 or token in allowed_generic_tokens:
                continue
            if token in allowed_tokens:
                continue
            if token.endswith("s") and token[:-1] in allowed_tokens:
                continue
            if token in seen:
                continue
            seen.add(token)
            unsupported.append(token)
        return unsupported

    def _payload_from_provider_output(self, *, output: LLMAnswerOutput, query: str, retrieval_result, detail_policy: DetailPolicy) -> dict:
        answer = output.answer.strip()
        if not answer:
            raise ValueError("LLM answer output is empty")
        if output.support_level != getattr(retrieval_result, "support_level", "unsupported"):
            raise ValueError("LLM answer changed the retrieval support level")
        available_fact_ids, available_evidence_ids = self._answer_ids(retrieval_result)
        available_fact_set = set(available_fact_ids)
        available_evidence_set = set(available_evidence_ids)
        used_fact_set = set(output.used_fact_ids)
        used_evidence_set = set(output.used_evidence_ids)
        if not used_fact_set or not used_evidence_set:
            raise ValueError("LLM answer omitted fact or evidence ids")
        if not used_fact_set.issubset(available_fact_set):
            raise ValueError("LLM answer cited unknown fact ids")
        if not used_evidence_set.issubset(available_evidence_set):
            raise ValueError("LLM answer cited unknown evidence ids")
        unsupported_phrases = self._unsupported_named_phrases_in_answer(answer=answer, query=query, retrieval_result=retrieval_result)
        if unsupported_phrases:
            raise ValueError(f"LLM answer introduced unsupported named phrases: {unsupported_phrases}")
        unsupported_tokens = self._unsupported_content_tokens_in_answer(answer=answer, query=query, retrieval_result=retrieval_result)
        if unsupported_tokens:
            raise ValueError(f"LLM answer introduced unsupported content tokens: {unsupported_tokens}")
        return self._payload(
            query=query,
            answer=answer,
            refused=False,
            retrieval_result=retrieval_result,
            detail_policy=detail_policy,
            used_fact_ids=output.used_fact_ids,
            used_evidence_ids=output.used_evidence_ids,
        )

    def _provider_fail_closed_payload(self, *, query: str, retrieval_result, detail_policy: DetailPolicy, answer: str) -> dict:
        fail_closed_result = retrieval_result.model_copy(
            update={
                "answerable": False,
                "refusal_category": "insufficient_evidence",
                "must_not_use_as_fact": True,
            }
        )
        return self._payload(
            query=query,
            answer=answer,
            refused=True,
            retrieval_result=fail_closed_result,
            detail_policy=detail_policy,
            used_fact_ids=[],
            used_evidence_ids=[],
        )

    def _temporal_conflict_answer(self, factual_hits) -> str:
        event_dates = {str(getattr(hit, "event_at", "") or "").strip() for hit in factual_hits if str(getattr(hit, "event_at", "") or "").strip()}
        if len(event_dates) > 1:
            return "I have conflicting memory evidence about the exact event date."
        valid_from_values = {str(getattr(hit, "valid_from", "") or "").strip() for hit in factual_hits if str(getattr(hit, "valid_from", "") or "").strip()}
        if not event_dates and len(valid_from_values) > 1:
            return "I have conflicting memory evidence about when that state began."
        return ""

    def _select_temporal_hit(self, factual_hits):
        for field in ("event_at", "valid_from", "observed_at"):
            hits = [hit for hit in factual_hits if str(getattr(hit, field, "") or "").strip()]
            if hits:
                return hits[0]
        return factual_hits[0] if factual_hits else None

    def _format_when_answer(self, hit) -> str:
        source, value = self._temporal_value(hit)
        if source == "event_at":
            return f"{hit.summary} The event date is {value}."
        if source == "valid_from":
            return f"{hit.summary} This has been true since {value}."
        if source == "observed_at":
            return f"{hit.summary} The exact event date is unknown; I only know it was recorded on {value}."
        return f"{hit.summary} The exact date is unknown."

    def build_answer(self, *, query: str, retrieval_result, detail_policy: DetailPolicy | None = None) -> dict:
        policy = detail_policy or getattr(retrieval_result, "detail_policy", "balanced")
        factual_hits = self._factual_hits(retrieval_result)
        is_when_query = query.strip().lower().startswith("when") or query.strip().lower().startswith("когда")
        if retrieval_result.hits and not factual_hits:
            sanitized = retrieval_result.model_copy(update={"hits": []})
            payload = self._payload(
                query=query,
                answer="I don't have confirmed memory evidence for that.",
                refused=True,
                retrieval_result=sanitized,
                detail_policy=policy,
            )
            self._record_usage(query=query, retrieval_result=sanitized, answer_payload=payload)
            return payload
        if is_when_query and factual_hits:
            conflict_answer = self._temporal_conflict_answer(factual_hits)
            if conflict_answer:
                payload = self._payload(
                    query=query,
                    answer=conflict_answer,
                    refused=True,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                )
                self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
                return payload
        if retrieval_result.support_level in {"unsupported", "ambiguous"}:
            payload = self._payload(
                query=query,
                answer="I don't have confirmed memory evidence for that.",
                refused=True,
                retrieval_result=retrieval_result,
                detail_policy=policy,
            )
            self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
            return payload
        if retrieval_result.support_level == "contradicted":
            fallback_supported = " ".join(hit.summary for hit in factual_hits).strip()
            fallback = "Confirmed memory conflicts with that claim."
            if fallback_supported:
                fallback = f"{fallback} {fallback_supported}".strip()
            answer = self._false_premise_answer(query=query, retrieval_result=retrieval_result, fallback=fallback)
            payload = self._payload(query=query, answer=answer, refused=True, retrieval_result=retrieval_result, detail_policy=policy)
            self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
            return payload
        if retrieval_result.support_level == "partial":
            supported = " ".join(hit.summary for hit in factual_hits).strip()
            unsupported = " ".join(retrieval_result.unsupported_claims).strip()
            if self._must_refuse_partial(query=query, retrieval_result=retrieval_result):
                answer = self._false_premise_answer(
                    query=query,
                    retrieval_result=retrieval_result,
                    fallback=supported or "I only have partial memory evidence for that.",
                )
                payload = self._payload(answer=answer, query=query, refused=True, retrieval_result=retrieval_result, detail_policy=policy)
                self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
                return payload
            if supported and unsupported:
                answer = f"{supported} However, {unsupported}"
            else:
                answer = supported or unsupported or "I only have partial memory evidence for that."
            payload = self._payload(query=query, answer=answer, refused=False, retrieval_result=retrieval_result, detail_policy=policy)
            self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
            return payload
        if self._should_use_provider_answer(retrieval_result):
            _fact_ids, evidence_ids = self._answer_ids(retrieval_result)
            if not factual_hits or not evidence_ids:
                payload = self._provider_fail_closed_payload(
                    query=query,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                    answer="I don't have confirmed memory evidence for that.",
                )
                self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
                return payload
            provider_payload = self._try_provider_answer(query=query, retrieval_result=retrieval_result, detail_policy=policy)
            if provider_payload is not None:
                return provider_payload
            if self.fail_closed_on_provider_error:
                payload = self._provider_fail_closed_payload(
                    query=query,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                    answer="I don't have confirmed memory evidence for that.",
                )
                self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
                return payload
        if is_when_query and factual_hits:
            first_hit = self._select_temporal_hit(factual_hits)
            if first_hit is not None:
                payload = self._payload(
                    query=query,
                    answer=self._format_when_answer(first_hit),
                    refused=False,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                )
                self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
                return payload
        payload = self._payload(
            query=query,
            answer=" ".join(hit.summary for hit in factual_hits),
            refused=False,
            retrieval_result=retrieval_result,
            detail_policy=policy,
        )
        self._record_usage(query=query, retrieval_result=retrieval_result, answer_payload=payload)
        return payload

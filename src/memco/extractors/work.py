from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


WORK_ROLE_PATTERNS = (
    re.compile(r"\bi\s+work\s+as\s+(?:an?\s+)?(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+(?:an?\s+)?(?P<value>(?:engineer|designer|manager|developer|teacher|writer|analyst|researcher)[^.!?\n]*)", re.IGNORECASE),
    re.compile(r"\bя\s+работаю\s+как\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+(?P<value>(?:инженер|дизайнер|менеджер|разработчик|учитель|писатель|аналитик|исследователь)[^.!?\n]*)", re.IGNORECASE),
)

WORK_PAST_ROLE_PATTERNS = (
    re.compile(r"\bi\s+used\s+to\s+work\s+as\s+(?:an?\s+)?(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+used\s+to\s+be\s+(?:an?\s+)?(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bраньше\s+я\s+работал(?:а)?\s+как\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bраньше\s+я\s+был(?:а)?\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

WORK_ORG_PATTERNS = (
    re.compile(r"\bi\s+work\s+at\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+used\s+to\s+work\s+at\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+работаю\s+в\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bраньше\s+я\s+работал(?:а)?\s+в\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

WORK_PROJECT_PATTERNS = (
    re.compile(r"\bi(?:'m| am)\s+building\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+строю\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

WORK_TOOL_PATTERNS = (
    re.compile(r"\bi\s+(?:use|work with)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+(?:использую|работаю\s+с)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

WORK_SKILL_PATTERNS = (
    re.compile(r"\bi\s+know\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+skilled\s+at\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+знаю\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+умею\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)


def _split_role_org(raw: str) -> tuple[str, str, list[str]]:
    value = clean_value(raw)
    role = value
    org = ""
    parts = re.split(r"\s+at\s+", value, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        role = clean_value(parts[0])
        org = clean_value(re.split(r"\s+(?:and|but)\s+i\s+", parts[1], maxsplit=1, flags=re.IGNORECASE)[0])
    reasons: list[str] = []
    if re.search(r"\s+at\s+", role, re.IGNORECASE):
        reasons.append("suspicious_work_payload")
    return role, org, reasons


def _with_review_reasons(context: ExtractionContext, *extra_reasons: str) -> list[str]:
    reasons = review_reasons_for_context(context)
    for reason in extra_reasons:
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def extract(context: ExtractionContext) -> list[dict]:
    candidates: list[dict] = []
    evidence = build_evidence(context)

    for pattern in WORK_ROLE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        title, org, quality_reasons = _split_role_org(match.group("value"))
        if not title:
            continue
        review_reasons = _with_review_reasons(context, *quality_reasons)
        payload = {"title": title, "role": title, "is_current": True}
        if org:
            payload["org"] = org
        summary = f"{context.subject_display} works as {title}."
        if org:
            summary = f"{context.subject_display} works as {title} at {org}."
        candidates.append(
            {
                "domain": "work",
                "category": "employment",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:employment:{slugify(title)}:{slugify(org)}",
                "payload": payload,
                "summary": summary,
                "confidence": 0.82 if context.person_id is not None else 0.58,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in WORK_PAST_ROLE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        role = clean_value(match.group("value"))
        if not role:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "work",
                "category": "role",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:role:{slugify(role)}",
                "payload": {"role": role, "is_current": False},
                "summary": f"{context.subject_display} used to work as {role}.",
                "confidence": 0.78 if context.person_id is not None else 0.54,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in WORK_ORG_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        org = clean_value(match.group("value"))
        if not org:
            continue
        review_reasons = review_reasons_for_context(context)
        is_current = "used to" not in context.text.lower()
        candidates.append(
            {
                "domain": "work",
                "category": "org",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:org:{slugify(org)}",
                "payload": {"org": org, "is_current": is_current},
                "summary": f"{context.subject_display} works at {org}.",
                "confidence": 0.8 if context.person_id is not None else 0.56,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in WORK_PROJECT_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        project = clean_value(match.group("value"))
        if not project:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "work",
                "category": "project",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:project:{slugify(project)}",
                "payload": {"project": project},
                "summary": f"{context.subject_display} is building {project}.",
                "confidence": 0.76 if context.person_id is not None else 0.54,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in WORK_TOOL_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        tool = clean_value(match.group("value"))
        if not tool:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "work",
                "category": "tool",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:tool:{slugify(tool)}",
                "payload": {"tool": tool},
                "summary": f"{context.subject_display} uses {tool}.",
                "confidence": 0.72 if context.person_id is not None else 0.5,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in WORK_SKILL_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        skill = clean_value(match.group("value"))
        if not skill:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "work",
                "category": "skill",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:skill:{slugify(skill)}",
                "payload": {"skill": skill},
                "summary": f"{context.subject_display} knows {skill}.",
                "confidence": 0.7 if context.person_id is not None else 0.48,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    return candidates

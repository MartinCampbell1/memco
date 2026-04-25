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
    re.compile(r"\bi\s+(?:worked\s+on|led|launched|shipped|maintain|contributed\s+to)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+строю\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

WORK_ENGAGEMENT_PATTERNS = (
    re.compile(
        r"\bi\s+(?P<engagement>consult|contract|freelance|advise)\s+for\s+(?P<client>[A-Z][A-Za-z0-9 &'_-]+?)"
        r"(?:\s+as\s+(?:an?\s+)?(?P<role>[^.!?\n]+?))?(?=$|\s+since\s+|\s+from\s+|[.!?\n])",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi\s+have\s+(?:an?\s+)?(?P<engagement>engagement|contract)\s+with\s+(?P<client>[A-Z][A-Za-z0-9 &'_-]+?)"
        r"(?:\s+as\s+(?:an?\s+)?(?P<role>[^.!?\n]+?))?(?=$|\s+since\s+|\s+from\s+|[.!?\n])",
        re.IGNORECASE,
    ),
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


DATE_VALUE_RE = r"(?:[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+|(?:19|20)\d{2})"


def _clean_work_entity(raw: str) -> str:
    value = clean_value(raw)
    value = re.split(
        r"\s+(?:with|on)\s+(?:the\s+)?[A-Za-z0-9 &'_-]+\s+team\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(r"\s+for\s+[A-Z][A-Za-z0-9 &'_-]+", value, maxsplit=1)[0]
    value = re.split(r"\s+(?:since|from|until|through)\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\s+where\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\s+and\s+(?:the\s+)?outcome\s+was\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return clean_value(value)


def _work_metadata(text: str, *, is_current: bool = True) -> dict:
    payload: dict = {"status": "current" if is_current else "past"}
    range_match = re.search(rf"\bfrom\s+(?P<start>{DATE_VALUE_RE})\s+(?:to|until|through)\s+(?P<end>{DATE_VALUE_RE})\b", text, re.IGNORECASE)
    if range_match:
        payload["start_date"] = clean_value(range_match.group("start"))
        payload["end_date"] = clean_value(range_match.group("end"))
        payload["status"] = "past"
    else:
        since_match = re.search(rf"\bsince\s+(?P<start>{DATE_VALUE_RE})\b", text, re.IGNORECASE)
        if since_match:
            payload["start_date"] = clean_value(since_match.group("start"))
        until_match = re.search(rf"\b(?:until|through)\s+(?P<end>{DATE_VALUE_RE})\b", text, re.IGNORECASE)
        if until_match:
            payload["end_date"] = clean_value(until_match.group("end"))
            payload["status"] = "past"
    team_match = re.search(r"\bon\s+(?:the\s+)?(?P<team>[A-Za-z0-9 &'_-]+?)\s+team\b", text, re.IGNORECASE)
    if not team_match:
        team_match = re.search(r"\bwith\s+(?:the\s+)?(?P<team>[A-Za-z0-9 &'_-]+?)\s+team\b", text, re.IGNORECASE)
    if team_match:
        payload["team"] = clean_value(team_match.group("team"))
    client_match = re.search(r"\bfor\s+(?P<client>[A-Z][A-Za-z0-9 &'_-]+?)(?=$|\s+as\s+|\s+with\s+|\s+on\s+|\s+since\s+|\s+from\s+|[.!?\n])", text)
    if client_match:
        payload["client"] = clean_value(client_match.group("client"))
    outcome_match = re.search(r"\b(?:outcome|result)\s+was\s+(?P<outcome>[^.!?\n]+)", text, re.IGNORECASE)
    if not outcome_match:
        outcome_match = re.search(r"\bwhich\s+(?P<outcome>(?:increased|reduced|improved|cut|saved|grew)[^.!?\n]+)", text, re.IGNORECASE)
    if outcome_match:
        payload["outcomes"] = [clean_value(outcome_match.group("outcome"))]
    collaborator_match = re.search(
        r"\bwith\s+(?P<people>[A-Z][A-Za-z0-9'_-]+(?:\s+(?:and|,)\s+[A-Z][A-Za-z0-9'_-]+)*)(?=\s+(?:on|for|since|from|where|and\s+the\s+outcome|\.|,)|[.!?\n]|$)",
        text,
    )
    if collaborator_match:
        collaborators = split_list_values(collaborator_match.group("people"))
        if collaborators and not any(item.lower().startswith("the ") or item.lower().endswith(" team") for item in collaborators):
            payload["collaborators"] = collaborators
    launched_match = re.search(rf"\b(?:launched|shipped)\s+(?:it\s+)?in\s+(?P<date>{DATE_VALUE_RE})\b", text, re.IGNORECASE)
    if launched_match:
        payload["status"] = f"launched in {clean_value(launched_match.group('date'))}"
    elif re.search(r"\b(?:shipped|launched)\b", text, re.IGNORECASE):
        payload["status"] = "completed"
    return {key: value for key, value in payload.items() if value not in ("", [], None)}


def split_list_values(raw: str) -> list[str]:
    value = clean_value(raw)
    if not value:
        return []
    value = re.split(r"\s+(?:and|but)\s+i\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\s+(?:for|on)\s+(?:projects?|work|my job)\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    parts = [clean_value(re.sub(r"^(?:and|or)\s+", "", part, flags=re.IGNORECASE)) for part in re.split(r"\s*,\s*|\s+\band\b\s+", value, flags=re.IGNORECASE)]
    parts = [part.strip(" .") for part in parts if part.strip(" .")]
    if len(parts) == 2 and parts[0].lower() == parts[1].lower():
        return [value]
    return parts or [value]


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
            payload["org"] = _clean_work_entity(org)
        payload.update(_work_metadata(context.text, is_current=True))
        summary = f"{context.subject_display} works as {title}."
        if org:
            summary = f"{context.subject_display} works as {title} at {payload['org']}."
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
        payload = {"role": _clean_work_entity(role), "is_current": False}
        payload.update(_work_metadata(context.text, is_current=False))
        candidates.append(
            {
                "domain": "work",
                "category": "role",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:role:{slugify(payload['role'])}",
                "payload": payload,
                "summary": f"{context.subject_display} used to work as {payload['role']}.",
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
        org = _clean_work_entity(match.group("value"))
        if not org:
            continue
        review_reasons = review_reasons_for_context(context)
        is_current = "used to" not in context.text.lower()
        payload = {"org": org, "is_current": is_current}
        payload.update(_work_metadata(context.text, is_current=is_current))
        candidates.append(
            {
                "domain": "work",
                "category": "org",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:org:{slugify(org)}",
                "payload": payload,
                "summary": f"{context.subject_display} works at {org}.",
                "confidence": 0.8 if context.person_id is not None else 0.56,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in WORK_ENGAGEMENT_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        engagement = clean_value(match.group("engagement")).lower()
        client = _clean_work_entity(match.group("client"))
        role = _clean_work_entity(match.groupdict().get("role") or "")
        if not engagement or not client:
            continue
        review_reasons = review_reasons_for_context(context)
        payload = {
            "engagement": {"consult": "consulting", "contract": "contracting", "freelance": "freelance", "advise": "advisory"}.get(engagement, engagement),
            "client": client,
            "status": "current",
        }
        if role:
            payload["role"] = role
        payload.update(_work_metadata(context.text, is_current=True))
        candidates.append(
            {
                "domain": "work",
                "category": "engagement",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:engagement:{slugify(payload['engagement'])}:{slugify(client)}",
                "payload": payload,
                "summary": f"{context.subject_display} has a {payload['engagement']} engagement with {client}.",
                "confidence": 0.74 if context.person_id is not None else 0.52,
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
        project = _clean_work_entity(match.group("value"))
        if not project:
            continue
        review_reasons = review_reasons_for_context(context)
        payload = {"project": project}
        payload.update(_work_metadata(context.text, is_current=not bool(re.search(r"\bworked\s+on\b", context.text, re.IGNORECASE))))
        candidates.append(
            {
                "domain": "work",
                "category": "project",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:work:project:{slugify(project)}",
                "payload": payload,
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
        tools = split_list_values(match.group("value"))
        if not tools:
            continue
        review_reasons = review_reasons_for_context(context)
        for tool in tools:
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
        skills = split_list_values(match.group("value"))
        if not skills:
            continue
        review_reasons = review_reasons_for_context(context)
        for skill in skills:
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

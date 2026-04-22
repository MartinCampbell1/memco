from __future__ import annotations

from fastapi import Header, HTTPException, status

from memco.config import load_settings
from memco.db import get_connection
from memco.runtime import ensure_runtime


def get_settings():
    settings = load_settings()
    ensure_runtime(settings)
    return settings


def require_api_auth(
    settings,
    authorization: str | None = Header(default=None),
    x_memco_token: str | None = Header(default=None),
) -> None:
    token = (settings.api.auth_token or "").strip()
    if not token:
        return
    provided = ""
    if x_memco_token:
        provided = x_memco_token.strip()
    elif authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = value.strip()
        elif not value:
            provided = authorization.strip()
    if provided != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_db(settings):
    return get_connection(settings.db_path)


def require_actor_context(actor, *, route_label: str) -> None:
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Actor context is required for {route_label}.",
        )


def build_internal_actor(settings, *, actor_id: str):
    policy = settings.api.actor_policies.get(actor_id)
    if policy is None:
        raise RuntimeError(f"Unknown internal actor policy: {actor_id}")
    from memco.models.retrieval import ActorContext

    return ActorContext(
        actor_id=actor_id,
        actor_type=policy.actor_type,
        auth_token=policy.auth_token,
        allowed_person_ids=list(policy.allowed_person_ids),
        allowed_domains=list(policy.allowed_domains),
        can_view_sensitive=policy.can_view_sensitive,
    )


def resolve_actor_context(settings, actor, *, route_label: str, allowed_actor_types: set[str], require_actor: bool = False):
    if actor is None:
        if settings.api.require_actor_scope or require_actor:
            require_actor_context(actor, route_label=route_label)
        return None
    policy = settings.api.actor_policies.get(actor.actor_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unknown actor for {route_label}.",
        )
    if policy.actor_type not in allowed_actor_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Actor type {policy.actor_type} is not allowed for {route_label}.",
        )
    if actor.auth_token != policy.auth_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid actor credentials for {route_label}.",
        )
    allowed_person_ids = actor.allowed_person_ids
    if policy.allowed_person_ids:
        if allowed_person_ids:
            allowed_person_ids = [item for item in allowed_person_ids if item in policy.allowed_person_ids]
        else:
            allowed_person_ids = list(policy.allowed_person_ids)
    allowed_domains = actor.allowed_domains
    if policy.allowed_domains:
        if allowed_domains:
            allowed_domains = [item for item in allowed_domains if item in policy.allowed_domains]
        else:
            allowed_domains = list(policy.allowed_domains)
    return actor.model_copy(
        update={
            "actor_type": policy.actor_type,
            "can_view_sensitive": policy.can_view_sensitive and actor.can_view_sensitive,
            "allowed_person_ids": allowed_person_ids,
            "allowed_domains": allowed_domains,
        }
    )

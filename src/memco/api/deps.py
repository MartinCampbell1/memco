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

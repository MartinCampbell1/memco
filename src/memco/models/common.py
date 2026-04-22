from __future__ import annotations

from typing import Literal

WorkspaceSlug = str
DomainName = Literal[
    "biography",
    "preferences",
    "social_circle",
    "work",
    "experiences",
    "psychometrics",
    "style",
]
FactStatus = Literal["active", "needs_review", "superseded", "deleted", "rejected"]

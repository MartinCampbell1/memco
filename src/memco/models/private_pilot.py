from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PrivatePilotGateReport(BaseModel):
    artifact_type: Literal["private_pilot_gate_report"] = "private_pilot_gate_report"
    ok: bool
    created_at: str
    git_commit: str
    checks: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from fastapi.testclient import TestClient

from memco.api.app import app
from memco.config import Settings, write_settings
from memco.db import get_connection
from memco.models.memory_fact import MemoryFactInput
from memco.models.retrieval import RetrievalRequest
from memco.models.private_pilot import PrivatePilotGateReport
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.runtime import ensure_runtime
from memco.services.backup_service import BackupService
from memco.services.candidate_service import CandidateService
from memco.services.consolidation_service import ConsolidationService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.eval_service import EvalService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.services.retrieval_service import RetrievalService
from memco.utils import isoformat_z


PILOT_PYTEST_FILES = (
    "tests/test_private_agent_semantic_regressions.py",
    "tests/test_benchmark_mode_does_not_disable_review_gate.py",
)


def _git_commit(project_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _prepare_fixture_root(root: Path) -> Settings:
    for suffix in ("", "-wal", "-shm"):
        db_file = root / "var" / "db" / f"memco.db{suffix}"
        if db_file.exists():
            db_file.unlink()
    settings = Settings(root=root)
    settings.runtime.profile = "fixture"
    settings.storage.engine = "sqlite"
    settings.llm.provider = "mock"
    settings.llm.model = "fixture"
    settings.llm.allow_mock_provider = True
    write_settings(settings)
    return ensure_runtime(settings)


def _run_pytest_summary(project_root: Path) -> dict:
    command = [sys.executable, "-m", "pytest", "-q", *PILOT_PYTEST_FILES]
    completed = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return {
        "name": "pytest_green",
        "ok": completed.returncode == 0,
        "command": command,
        "summary": lines[-1] if lines else "",
        "returncode": completed.returncode,
    }


def _check(name: str, ok: bool, **details) -> dict:
    return {"name": name, "ok": ok, **details}


def _run_backup_dry_run(settings: Settings) -> dict:
    service = BackupService()
    backup_path = settings.root / "var" / "backups" / "private-pilot-full-backup.json"
    with get_connection(settings.db_path) as conn:
        export_summary = service.export_backup(
            conn,
            output_path=backup_path,
            storage_engine=settings.storage.engine,
            mode="full",
        )
    verify_summary = service.verify_backup(backup_path)
    restore_summary = service.restore_dry_run(backup_path)
    return {
        "export": export_summary,
        "verify": verify_summary,
        "restore_dry_run": restore_summary,
    }


def _actor(settings: Settings) -> dict:
    policy = settings.api.actor_policies["dev-owner"]
    return {
        "actor_id": "dev-owner",
        "actor_type": policy.actor_type,
        "auth_token": policy.auth_token,
        "allowed_person_ids": [],
        "allowed_domains": [],
        "can_view_sensitive": policy.can_view_sensitive,
    }


def _seed_api_smoke_fact(settings: Settings) -> None:
    fact_repo = FactRepository()
    source_repo = SourceRepository()
    consolidation = ConsolidationService()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Pilot Alice",
            slug="pilot-alice",
            person_type="human",
            aliases=["Pilot Alice"],
        )
        source_id = source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path="var/raw/private-pilot-api-smoke.md",
            source_type="note",
            origin_uri="/tmp/private-pilot-api-smoke.md",
            title="private-pilot-api-smoke",
            sha256="private-pilot-api-smoke",
            parsed_text="Pilot Alice lives in Lisbon.",
        )
        consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=int(person["id"]),
                domain="biography",
                category="residence",
                canonical_key="pilot-alice:biography:residence:lisbon",
                payload={"city": "Lisbon"},
                summary="Pilot Alice lives in Lisbon.",
                source_kind="explicit",
                confidence=0.95,
                observed_at="2026-04-28T00:00:00Z",
                source_id=source_id,
                quote_text="Pilot Alice lives in Lisbon.",
            ),
        )


@contextmanager
def _temporary_env(key: str, value: str) -> Iterator[None]:
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _run_api_memory_context_smoke(settings: Settings) -> dict:
    _seed_api_smoke_fact(settings)
    with _temporary_env("MEMCO_ROOT", str(settings.root)):
        client = TestClient(app)
        supported = client.post(
            "/v1/agent/memory-context",
            json={
                "person_slug": "pilot-alice",
                "query": "Where does Pilot Alice live?",
                "mode": "retrieval_only",
                "max_facts": 5,
                "include_evidence": True,
                "actor": _actor(settings),
            },
        )
        unsupported = client.post(
            "/v1/agent/memory-context",
            json={
                "person_slug": "pilot-alice",
                "query": "Does Pilot Alice have a sister?",
                "mode": "retrieval_only",
                "max_facts": 5,
                "include_evidence": True,
                "actor": _actor(settings),
            },
        )
    supported_payload = supported.json() if supported.status_code == 200 else {}
    unsupported_payload = unsupported.json() if unsupported.status_code == 200 else {}
    supported_context = supported_payload.get("memory_context") or []
    return {
        "supported_status": supported.status_code,
        "unsupported_status": unsupported.status_code,
        "supported_answerable": supported_payload.get("answerable"),
        "supported_context_count": len(supported_context),
        "supported_evidence_count": sum(len(item.get("evidence") or []) for item in supported_context),
        "unsupported_answerable": unsupported_payload.get("answerable"),
        "unsupported_support_level": unsupported_payload.get("support_level"),
    }


def _run_review_gate_smoke(settings: Settings) -> dict:
    source_path = settings.root / "var" / "raw" / "private-pilot-review-gate.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "speaker": "Pilot Review Alice",
                        "timestamp": "2026-04-28T10:00:00Z",
                        "text": "I moved to Nuuk.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    fact_repo = FactRepository()
    candidate_repo = CandidateRepository()
    with get_connection(settings.db_path) as conn:
        person = fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name="Pilot Review Alice",
            slug="pilot-review-alice",
            person_type="human",
            aliases=["Pilot Review Alice"],
        )
        imported = IngestService().import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source_path,
            source_type="json",
        )
        conversation = ConversationIngestService().import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
        )
        candidates = CandidateService(
            extraction_service=ExtractionService.from_settings(settings),
            candidate_repository=candidate_repo,
        ).extract_from_conversation(
            conn,
            workspace_slug="default",
            conversation_id=conversation.conversation_id,
        )
        active_facts = fact_repo.list_facts(
            conn,
            workspace_slug="default",
            person_id=int(person["id"]),
            status="active",
        )
        retrieval = RetrievalService().retrieve(
            conn,
            RetrievalRequest(
                workspace="default",
                person_slug="pilot-review-alice",
                query="Where does Pilot Review Alice live?",
                limit=5,
            ),
        )
    candidate_statuses = [str(candidate["candidate_status"]) for candidate in candidates]
    confirmed_count = len(active_facts) + len(retrieval.hits)
    benchmark_env_enabled = os.environ.get("MEMCO_BENCHMARK_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "candidate_count": len(candidates),
        "candidate_statuses": candidate_statuses,
        "published_candidate_count": sum(1 for status in candidate_statuses if status == "published"),
        "active_fact_count": len(active_facts),
        "retrieval_hit_count": len(retrieval.hits),
        "retrieval_answerable": retrieval.answerable,
        "retrieval_support_level": retrieval.support_level,
        "pending_candidates_returned_as_confirmed": confirmed_count,
        "benchmark_mode_env_enabled": benchmark_env_enabled,
    }


def _personal_metrics(personal_eval: dict) -> dict:
    metrics = personal_eval.get("metrics") or {}
    return {
        "personal_memory_total": personal_eval.get("total", 0),
        "personal_memory_passed": personal_eval.get("passed", 0),
        "unsupported_claims_answered_as_fact": metrics.get("unsupported_premise_answered_as_fact", 0),
        "supported_answers_missing_evidence": metrics.get("evidence_missing_on_supported_answers", 0),
        "cross_person_contamination": metrics.get("cross_person_contamination", 0),
    }


def build_private_pilot_gate_report(*, project_root: Path, root: Path) -> dict:
    settings = _prepare_fixture_root(root)
    eval_service = EvalService()
    goldens_dir = project_root / "eval" / "personal_memory_goldens"

    checks: list[dict] = []
    checks.append(_run_pytest_summary(project_root))

    personal_eval = eval_service.run_personal_memory(project_root=settings.root, goldens_dir=goldens_dir)
    checks.append(
        _check(
            "personal_memory_eval_green",
            bool(personal_eval.get("ok")),
            passed=personal_eval.get("passed"),
            total=personal_eval.get("total"),
        )
    )

    backup = _run_backup_dry_run(settings)
    checks.append(
        _check(
            "backup_export_verify_ok",
            bool(backup["export"].get("ok") and backup["verify"].get("ok") and backup["restore_dry_run"].get("ok")),
            export_ok=backup["export"].get("ok"),
            verify_ok=backup["verify"].get("ok"),
            restore_dry_run_ok=backup["restore_dry_run"].get("ok"),
        )
    )

    api_smoke = _run_api_memory_context_smoke(settings)
    checks.append(
        _check(
            "api_memory_context_smoke_ok",
            api_smoke["supported_status"] == 200
            and api_smoke["unsupported_status"] == 200
            and api_smoke["supported_answerable"] is True
            and api_smoke["supported_context_count"] > 0
            and api_smoke["supported_evidence_count"] > 0
            and api_smoke["unsupported_answerable"] is False,
            **api_smoke,
        )
    )

    review_gate_smoke = _run_review_gate_smoke(settings)
    metrics = _personal_metrics(personal_eval)
    metrics["pending_candidates_returned_as_confirmed"] = review_gate_smoke["pending_candidates_returned_as_confirmed"]
    metrics["api_memory_context_supported_evidence_count"] = api_smoke["supported_evidence_count"]

    checks.extend(
        [
            _check("unsupported_claims_refused", metrics["unsupported_claims_answered_as_fact"] == 0),
            _check("supported_answers_have_evidence", metrics["supported_answers_missing_evidence"] == 0),
            _check(
                "pending_review_not_leaked",
                metrics["pending_candidates_returned_as_confirmed"] == 0
                and review_gate_smoke["candidate_count"] > 0
                and review_gate_smoke["published_candidate_count"] == 0,
                **review_gate_smoke,
            ),
            _check(
                "no_benchmark_mode_leakage",
                not review_gate_smoke["benchmark_mode_env_enabled"]
                and review_gate_smoke["published_candidate_count"] == 0
                and review_gate_smoke["active_fact_count"] == 0,
                benchmark_mode="not_enabled",
                **review_gate_smoke,
            ),
        ]
    )

    failures = [check["name"] for check in checks if not check.get("ok")]
    report = PrivatePilotGateReport(
        ok=not failures,
        created_at=isoformat_z(),
        git_commit=_git_commit(project_root),
        checks=checks,
        metrics=metrics,
        failures=failures,
    )
    return report.model_dump(mode="json")


def run_private_pilot_gate(*, project_root: Path, root: Path | None = None) -> dict:
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        return build_private_pilot_gate_report(project_root=project_root, root=root)
    with TemporaryDirectory(prefix="memco-private-pilot-gate-") as tmpdir:
        return build_private_pilot_gate_report(project_root=project_root, root=Path(tmpdir))

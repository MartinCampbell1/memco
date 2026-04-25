from __future__ import annotations

from uuid import uuid4

from memco.models.memory_fact import MemoryFactInput
from memco.repositories.fact_repository import FactRepository


class ConsolidationService:
    def __init__(self, fact_repository: FactRepository | None = None) -> None:
        self.fact_repository = fact_repository or FactRepository()
        self.last_report: dict = self._empty_report()

    def add_fact(
        self,
        conn,
        payload: MemoryFactInput,
        *,
        locator: dict | None = None,
        source_chunk_id: int | None = None,
        source_segment_id: int | None = None,
        session_id: int | None = None,
    ) -> dict:
        person_id = payload.person_id
        if person_id is None:
            person_id = self.fact_repository.resolve_person_id(
                conn,
                workspace_slug=payload.workspace,
                person_slug=payload.person_slug,
            )
        fact = self.fact_repository.add_fact(
            conn,
            workspace_slug=payload.workspace,
            person_id=person_id,
            domain=payload.domain,
            category=payload.category,
            subcategory=payload.subcategory,
            canonical_key=payload.canonical_key,
            payload=payload.payload,
            summary=payload.summary,
            source_kind=payload.source_kind,
            confidence=payload.confidence,
            observed_at=payload.observed_at,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            event_at=payload.event_at,
            source_id=payload.source_id,
            quote_text=payload.quote_text,
            source_chunk_id=source_chunk_id,
            source_segment_id=source_segment_id,
            session_id=session_id,
            locator=locator,
        )
        self.last_report = self._build_report(conn, workspace_slug=payload.workspace, facts=[fact])
        return fact

    def add_facts(self, conn, payloads: list[MemoryFactInput]) -> dict:
        facts = []
        operations = []
        for payload in payloads:
            fact = self.add_fact(conn, payload)
            facts.append(fact)
            operations.extend(self.last_report["operations"])
        fresh_facts = [self.fact_repository.get_fact(conn, fact_id=int(fact["id"])) for fact in facts]
        fact_by_id = {int(fact["id"]): fact for fact in fresh_facts}
        for operation in operations:
            current = fact_by_id.get(int(operation["fact_id"]))
            if current is not None:
                operation["final_status"] = current.get("status")
                operation["final_superseded_by_fact_id"] = current.get("superseded_by_fact_id")
        report = self._build_report_from_operations(operations)
        self.last_report = report
        return {"facts": fresh_facts, "report": report}

    def _empty_report(self) -> dict:
        return {
            "run_id": uuid4().hex,
            "total": 0,
            "inserted": 0,
            "inserted_active": 0,
            "merged": 0,
            "superseded": 0,
            "superseded_existing": 0,
            "inserted_historical": 0,
            "needs_review": 0,
            "conflicts": [],
            "by_domain": {},
            "operations": [],
        }

    def _latest_operation_for_fact(self, conn, *, workspace_slug: str, fact_id: int) -> dict | None:
        operations = self.fact_repository.list_operations(
            conn,
            workspace_slug=workspace_slug,
            target_fact_id=fact_id,
            limit=1,
        )
        return operations[0] if operations else None

    def _build_report(self, conn, *, workspace_slug: str, facts: list[dict]) -> dict:
        operations = [
            self._operation_report_entry(
                fact=fact,
                operation=self._latest_operation_for_fact(
                    conn,
                    workspace_slug=workspace_slug,
                    fact_id=int(fact["id"]),
                ),
            )
            for fact in facts
        ]
        return self._build_report_from_operations(operations)

    def _operation_report_entry(self, *, fact: dict, operation: dict | None) -> dict:
        operation_type = str(operation["operation_type"]) if operation is not None else "unknown"
        before = operation.get("before", {}) if operation is not None else {}
        return {
            "fact_id": int(fact["id"]),
            "operation_type": operation_type,
            "domain": str(fact.get("domain") or ""),
            "category": str(fact.get("category") or ""),
            "canonical_key": fact.get("canonical_key"),
            "status": fact.get("status"),
            "final_status": fact.get("status"),
            "supersedes_fact_id": fact.get("supersedes_fact_id"),
            "superseded_by_fact_id": fact.get("superseded_by_fact_id"),
            "final_superseded_by_fact_id": fact.get("superseded_by_fact_id"),
            "conflict_kind": before.get("conflict_kind", ""),
            "reason": operation.get("reason", "") if operation is not None else "",
        }

    def _build_report_from_operations(self, operations: list[dict]) -> dict:
        report = self._empty_report()
        report["total"] = len(operations)
        for operation in operations:
            operation_type = str(operation.get("operation_type") or "unknown")
            domain = str(operation.get("domain") or "")
            domain_report = report["by_domain"].setdefault(
                domain,
                {
                    "total": 0,
                    "inserted": 0,
                    "inserted_active": 0,
                    "merged": 0,
                    "superseded": 0,
                    "superseded_existing": 0,
                    "inserted_historical": 0,
                    "needs_review": 0,
                },
            )
            domain_report["total"] += 1
            if operation_type == "merge":
                bucket = "merged"
            elif operation.get("status") == "superseded" and operation.get("superseded_by_fact_id") is not None:
                bucket = "inserted_historical"
            elif operation.get("supersedes_fact_id") is not None:
                bucket = "superseded_existing"
            else:
                bucket = "inserted_active"
            if operation_type == "add":
                report["inserted"] += 1
                domain_report["inserted"] += 1
            report[bucket] += 1
            domain_report[bucket] += 1
            if operation.get("status") == "needs_review":
                report["needs_review"] += 1
                domain_report["needs_review"] += 1
            if operation.get("supersedes_fact_id") is not None:
                report["superseded"] += 1
                domain_report["superseded"] += 1
                report["conflicts"].append(
                    {
                        "fact_id": operation["fact_id"],
                        "supersedes_fact_id": operation["supersedes_fact_id"],
                        "domain": operation["domain"],
                        "category": operation["category"],
                        "conflict_kind": operation.get("conflict_kind", ""),
                        "reason": operation.get("reason", ""),
                    }
                )
            report["operations"].append(operation)
        return report

    def mark_deleted(self, conn, *, fact_id: int, reason: str = "") -> dict:
        return self.fact_repository.mark_fact_status(
            conn,
            fact_id=fact_id,
            status="deleted",
            reason=reason or "deleted",
        )

    def restore(self, conn, *, fact_id: int, reason: str = "") -> dict:
        return self.fact_repository.mark_fact_status(
            conn,
            fact_id=fact_id,
            status="active",
            reason=reason or "restored",
        )

    def rollback(self, conn, *, operation_id: int, reason: str = "") -> dict:
        return self.fact_repository.rollback_operation(
            conn,
            operation_id=operation_id,
            reason=reason or "rolled back",
        )

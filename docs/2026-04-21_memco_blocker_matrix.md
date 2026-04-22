# Memco Blocker Matrix

Date: 2026-04-21

Historical note:

- This matrix reflects the earlier pre-remediation snapshot.
- It is not the active repo-local release gate.
- For the current release decision, use [2026-04-21_memco_release_readiness_gate.md](2026-04-21_memco_release_readiness_gate.md).
- For the accepted current contract, use [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md) and [2026-04-22_memco_contract_decision.md](2026-04-22_memco_contract_decision.md).

| Issue | Breaks single-user practical use? | Breaks spec compliance? | Severity | Notes |
|---|---|---|---|---|
| SQLite instead of PostgreSQL + Docker Compose + migrations | No | Yes | High | Acceptable for a private prototype, not acceptable for an honest `P0a done` claim. |
| Missing actor/viewer request context | Usually no | Yes | High | Important for multi-user / policy correctness; low immediate pain for one private owner. |
| Missing generic `source_segments` model | No today | Yes | Medium | Structural mismatch; future ingestion formats will feel it first. |
| Simplified candidate lifecycle | Not immediately | Yes | Medium | Works operationally, but weaker than the documented truth-promotion contract. |
| Missing confidence gate before publish | Potentially | Yes | Medium | Can matter if extraction quality worsens or future LLM path is added. |
| Supersede rollback bug | Yes | Yes | Critical | Real correctness defect; reproduced manually. |
| 7-case eval instead of acceptance-sized report | No immediate runtime break | Yes | High | Stops honest release readiness, not day-one private usage. |
| No `IMPLEMENTATION_NOTES.md` | No | Yes | Medium | Honesty/documentation gap. |
| No provider-agnostic LLM adapter | No for current rule-based slice | Yes | Medium | Architectural drift from the brief. |
| No token accounting | No | Yes | Medium | Latency exists, token accounting does not. |
| CLI lacks `source -> conversation` step | Yes, ergonomically | Not clearly a brief blocker | Medium | The system is usable, but not through one clean CLI-only surface. |
| No public auth / profiles / registration flows | No | No for private slice | Low | Explicitly not needed for the user’s stated single-user scenario. |

## Bottom line

For the owner-as-only-user scenario:

- **Critical real blocker:** supersede rollback bug
- **Meaningful operator friction:** incomplete CLI-only workflow
- **Everything else above is mostly about honest scope/spec compliance rather than immediate private usability**

For the claim “the project is fully finished per documentation”:

- the answer is **no**

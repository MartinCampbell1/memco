# Memco Contract Decision

Date: 2026-04-22
Status: accepted for current repo-local work

## Decision

For the current repository and current branch-local iteration, the target contract is:

- [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md)

The original brief:

- [synthius_mem_programmer_spec_v1_1_agent_ready.md](synthius_mem_programmer_spec_v1_1_agent_ready.md)

remains:

- architecture/reference input
- backlog source
- the source of the strict original acceptance wording

It is not the sole controlling contract for current repo-local release claims.

## Why This Decision Exists

Without an explicit contract decision, the repository falls back into an ambiguous state where:

- private release evidence is green
- no-Docker Postgres runtime evidence is green
- strict original-brief closure is still blocked by the Docker Compose wording
- but contributors may still talk as if all of those are the same question

This decision separates those questions deliberately.

## Effective Meaning

For ongoing work in this repository:

- the repo-local execution brief is the target contract
- the release gate should be read against that repo-local contract first
- strict original-brief readiness remains a separate explicit question

## What Counts As Green Now

Under the accepted repo-local contract:

- private release readiness may be `GO`
- no-Docker Postgres operational readiness may be `GO`
- repo-local brief convergence may be treated as the primary target for further work

## What Does Not Change

This decision does not mean:

- the original brief text was silently rewritten
- strict original-brief readiness automatically became green
- Docker is now required again on this machine

If someone asks the strict original question, the answer must still come from:

- [2026-04-21_memco_release_readiness_gate.md](2026-04-21_memco_release_readiness_gate.md)
- [2026-04-22_memco_repo_local_status_snapshot.md](2026-04-22_memco_repo_local_status_snapshot.md)

and not from this decision alone.

## Operational Consequence

From this point forward:

- continue implementation and release claims against the repo-local execution brief
- keep strict original-brief readiness as a separate reference/backlog-only track
- do not reopen Docker work unless it is explicitly requested

Companion decision:

- [2026-04-22_memco_original_brief_track_decision.md](2026-04-22_memco_original_brief_track_decision.md)

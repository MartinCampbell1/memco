# Memco Original Brief Track Decision

Date: 2026-04-22
Status: accepted for current repo-local release management

## Decision

For current repo-local release management in this repository, the original execution brief is moved to a reference/backlog-only track.

The original brief:

- [synthius_mem_programmer_spec_v1_1_agent_ready.md](synthius_mem_programmer_spec_v1_1_agent_ready.md)

remains important as:

- architecture reference
- backlog source
- a record of the original stricter acceptance wording

But it is not an active release contract for current repo-local work.

## Why

Current repo-local work now has an accepted target contract:

- [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md)

Keeping the original brief as an equally active release question would recreate the same ambiguity that has already been cleaned up:

- private release can be green
- no-Docker Postgres can be green
- repo-local target contract can be explicit
- yet contributors would still keep treating strict original brief closure as if it were the current release target

That is no longer the intended operating model for this repository.

## Effective Meaning

From now on:

- release claims should be made against the repo-local execution brief
- strict original-brief status may still be reported if someone asks
- strict original-brief status is not an active blocker for current repo-local release management

## Reopen Rule

The strict original brief track may be reopened only if one of these happens:

1. someone explicitly asks to target the original brief again
2. the accepted repo-local contract is replaced
3. Docker-based convergence is deliberately brought back into the accepted workflow

Until then, treat the original brief as:

- reference
- backlog
- explicit non-controlling acceptance history

# Memco

Memco is currently a local-first persona-memory system with evidence-first retrieval, a strong private single-user path, and a verified no-Docker Postgres runtime path on this machine.

## Current Product Contract

This repository should be read as:

- a local-first persona-memory system with a fully working private/operator path
- a real memory loop that can import conversation-like sources, extract candidates, publish facts, retrieve supported facts, refuse unsupported claims, and roll back fact lifecycle operations

This repository should not be read as:

- a broad public SaaS-style multi-user product beyond the currently documented API and operating model
- a claim that Docker Compose is the preferred day-to-day runtime path on this machine
- a claim that the strict Docker Compose requirement from the original execution brief has already been waived

The current honest status is:

- usable for a technical private owner/operator
- has a verified no-Docker Postgres operating path on this machine
- should still be treated as `private release = GO` and `strict original-brief readiness = not yet a clean yes` while the original brief still names Docker Compose explicitly

## Stage A Actor Contract

For the current private release, Memco uses an explicit Stage A exception:

- owner-only local usage
- simple shared-token/dev-local access
- private local workflows can still run without an API actor payload because the CLI/local path does not go through the public API

This exception applies to the private CLI/local workflow. It does not describe the user-facing API contract.

For the current codebase:

- local owner mode keeps this Stage A exception through the CLI/local path
- the user-facing API contract for `chat` / `retrieve` now requires an actor block by default
- retrieval is filtered by allowed person/domain scope

## Deviation Notes

Implementation deviations and known scope limits are tracked in [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md).

Read that file before making any claim that the repository strictly satisfies the original execution brief.
Read that file together with [docs/synthius_mem_execution_brief.md](docs/synthius_mem_execution_brief.md) and [docs/2026-04-21_memco_release_readiness_gate.md](docs/2026-04-21_memco_release_readiness_gate.md), which are the current source of truth for the repo-local contract and the private/original-brief split.

The explicit contract decision for current repo-local work lives in [docs/2026-04-22_memco_contract_decision.md](docs/2026-04-22_memco_contract_decision.md).
The original execution brief is kept as a reference/backlog-only track for current repo-local release management, documented in [docs/2026-04-22_memco_original_brief_track_decision.md](docs/2026-04-22_memco_original_brief_track_decision.md).

## Single-User Setup And Use

Replace the uppercase placeholders with values from the previous JSON output:

```bash
ROOT=/tmp/memco-demo
SOURCE_JSON=/absolute/path/to/conversation.json

uv run memco init-db --root "$ROOT"
uv run memco person-upsert "Alice" --slug alice --alias Alice --root "$ROOT"
uv run memco import "$SOURCE_JSON" --source-type json --root "$ROOT"
uv run memco conversation-import --latest-source --root "$ROOT"
uv run memco candidate-extract --latest-conversation --root "$ROOT"
uv run memco candidate-publish --latest-candidate --root "$ROOT"
uv run memco retrieve "Where does Alice live?" alice --root "$ROOT"
uv run memco chat "Where does Alice live?" alice --root "$ROOT"
uv run memco chat "Does Alice work at Stripe?" alice --root "$ROOT"
uv run memco fact-operations --latest-target-fact --operation-type superseded --root "$ROOT"
uv run memco fact-rollback --latest-operation --operation-type superseded --reason "undo supersede" --root "$ROOT"
```

Current CLI flow supports the private single-user operator path end to end, including `source -> conversation` via `conversation-import`.

In the simple single-user path, `--latest-source`, `--latest-conversation`, `--latest-candidate`, `--latest-target-fact`, and `--latest-operation` reduce manual ID handoff between the main operator steps.

For `candidate-publish`, `--latest-candidate` means the literal newest candidate in the workspace. If that newest candidate is not publishable yet, the command fails closed instead of silently publishing an older one.

If the workspace contains multiple people or domains, scope that shortcut explicitly with `--person-slug` and/or `--domain`.

For review-driven paths, the same pattern now works through `review-resolve approved --latest-review --candidate-person-slug ...` and `--candidate-target-person-slug ...`, so the operator can stay on slugs instead of numeric queue/person IDs.

Typical review-driven branch:

```bash
uv run memco review-list --status pending --person-slug alice --root "$ROOT"
uv run memco review-resolve approved --latest-review --person-slug alice --candidate-person-slug alice --candidate-target-person-slug bob --publish --reason "resolved review path" --root "$ROOT"
```

In mixed workspaces, `retrieval-log-list --person-slug alice` lets the operator inspect one person’s redacted retrieval activity without scanning the whole workspace log stream.

For unresolved-speaker flows, `conversation-speaker-resolve SPEAKER_KEY --latest-conversation --person-slug ...` removes the last manual conversation-id handoff from that branch too.

For manual truth-store edits, `fact-add ... --latest-source` removes the remaining source-id handoff from the manual fact path.

The documented private-release acceptance checklist lives in [docs/2026-04-21_memco_private_release_gate.md](docs/2026-04-21_memco_private_release_gate.md).

The top-level readiness split between `private release` and `strict original execution-brief readiness` lives in [docs/2026-04-21_memco_release_readiness_gate.md](docs/2026-04-21_memco_release_readiness_gate.md).

The canonical repo-local remediation plan now lives in [docs/plans/2026-04-21_memco_full_fix_plan.md](docs/plans/2026-04-21_memco_full_fix_plan.md).

If your actual use is “seed once, then connect Hermes,” the shortest one-time loading path is:

```bash
uv run memco ingest-pipeline /absolute/path/to/conversation.json --person-display-name "Alice" --person-slug alice --alias Alice --root "$ROOT"
```

That one command:

- optionally upserts the person
- imports the source
- creates the conversation
- extracts candidates
- auto-publishes validated candidates
- reports any pending review items you still need to resolve before using Memco through the API

There is now a matching HTTP path for the same one-shot load:

```bash
curl -sS http://127.0.0.1:8788/v1/ingest/pipeline \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace": "default",
    "path": "/absolute/path/to/conversation.json",
    "source_type": "json",
    "person_display_name": "Alice",
    "person_slug": "alice",
    "aliases": ["Alice"]
  }'
```

If you prefer inline text instead of a file path:

```bash
curl -sS http://127.0.0.1:8788/v1/ingest/pipeline \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace": "default",
    "text": "Alice: I moved to Lisbon.",
    "source_type": "text",
    "title": "inline-seed"
  }'
```

For `chat` and `retrieve`, the API still requires an `actor` block even in private mode.

The active repo-local release gate can be run locally with:

```bash
uv run memco release-check
```

By default it resolves the nearest Memco checkout above the current working directory.
If you are running it from elsewhere, pass an explicit root:

```bash
uv run memco release-check --project-root /absolute/path/to/memco
```

To persist the gate artifact directly to disk:

```bash
uv run memco release-check --output /absolute/path/to/release-check.json
```

If you also want to fold the no-Docker Postgres smoke into the same release artifact:

```bash
uv run memco release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'
```

That variant runs the same active repo-local gate plus a no-Docker Postgres smoke and returns one combined JSON artifact.

## Recommended Runtime Paths

For this machine, the recommended non-SQLite runtime path is:

- PostgreSQL via any reachable Postgres instance
- versioned SQL migrations
- API running with `MEMCO_STORAGE_ENGINE=postgres`

Current private release work still defaults to SQLite for the local single-user slice.

Preferred no-Docker path:

```bash
export MEMCO_STORAGE_ENGINE=postgres
export MEMCO_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME'
uv run memco postgres-bootstrap memco_db --root "$ROOT"
uv run memco init-db --root "$ROOT"
uv run memco-api
curl http://127.0.0.1:8788/health
```

This avoids Docker entirely and is the preferred operational path on this machine.

The repository still contains `Dockerfile` and `docker-compose.yml` as repo artifacts for spec-convergence work, but they are not part of the recommended local workflow and will not be used on this machine unless explicitly requested.

Focused no-Docker guide:

- [docs/2026-04-22_postgres_without_docker.md](docs/2026-04-22_postgres_without_docker.md)

Quick smoke on a running local Postgres:

```bash
MEMCO_DATABASE_URL='postgresql://USER@127.0.0.1:5432/postgres' \
uv run memco postgres-smoke
```

# Memco

Memco is currently a local, private, operator-controlled, review-gated persona-memory system with evidence-first retrieval and a verified no-Docker Postgres runtime path on this machine.

## Current Product Contract

This repository should be read as:

- a local-first persona-memory system with a working private, operator-controlled, review-gated path
- a real memory loop that can import conversation-like sources, extract candidates, publish facts, retrieve supported facts, refuse unsupported claims, and roll back fact lifecycle operations

This repository should not be read as:

- a broad public SaaS-style multi-user product beyond the currently documented API and operating model
- a claim that Docker Compose is the preferred day-to-day runtime path on this machine
- a claim that the strict Docker Compose requirement from the original execution brief has already been waived
- a claim that WhatsApp or Telegram export parsers are already part of the current repo-local ingestion contract

The current honest status is:

- usable as a local private operator-controlled memory lifecycle for a technical owner/operator once local live-provider credentials are supplied
- has a verified no-Docker Postgres operating path on this machine
- private release claim requires a fresh `release-readiness-check` artifact with live smoke
- strict original-brief readiness is still not a clean yes while the original brief still names Docker Compose explicitly

No release claim in this repository should be read as a universal memory substrate or fully autonomous production memory. The supported scope is local/private/operator-controlled/review-gated unless a future contract explicitly says otherwise.

Current repo-local ingestion scope:

- implemented and supported now: `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf`
- explicitly not part of the current repo-local contract: `WhatsApp`, `Telegram`
- `WhatsApp` / `Telegram` remain roadmap/reference-track parser targets and should not be implied as currently shipped support

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
The fastest repo-local status summary now lives in [docs/2026-04-22_memco_repo_local_status_snapshot.md](docs/2026-04-22_memco_repo_local_status_snapshot.md).
The current private release closure lives in [docs/2026-04-24_memco_release_closure.md](docs/2026-04-24_memco_release_closure.md).

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
uv run memco review-dashboard --status pending --person-slug alice --root "$ROOT"
uv run memco review-resolve approved --latest-review --person-slug alice --candidate-person-slug alice --candidate-target-person-slug bob --publish --reason "resolved review path" --root "$ROOT"
```

In mixed workspaces, `retrieval-log-list --person-slug alice` lets the operator inspect one person’s redacted retrieval activity without scanning the whole workspace log stream.

`review-dashboard` is the compact CLI review UX: it combines queue items, candidate cards, evidence previews, low-confidence/sensitive/psychometrics flags, and merge/supersede previews before the operator resolves or publishes anything.

For unresolved-speaker flows, `conversation-speaker-resolve SPEAKER_KEY --latest-conversation --person-slug ...` removes the last manual conversation-id handoff from that branch too.

For manual truth-store edits, `fact-add ... --latest-source` removes the remaining source-id handoff from the manual fact path.

The documented private-release acceptance checklist lives in [docs/2026-04-21_memco_private_release_gate.md](docs/2026-04-21_memco_private_release_gate.md).

The required private agent-memory pilot sequence lives in [docs/PRIVATE_PILOT_RUNBOOK.md](docs/PRIVATE_PILOT_RUNBOOK.md).

Backup/export/restore checks are available through the backup command group:

```bash
uv run memco backup export --mode audit --output var/backups/memco-audit-export.json --root "$ROOT"
uv run memco backup verify var/backups/memco-audit-export.json
MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup export --mode full --encrypted --output var/backups/memco-full-backup.json.enc --root "$ROOT"
MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup restore-dry-run var/backups/memco-full-backup.json.enc
```

Audit exports redact raw source/message/evidence text. Full encrypted exports are the restore-dry-run path and should remain private runtime artifacts.

Eval and chat service wiring now expose production-style `token_accounting.production_accounting`: stage tokens for extraction/planner/retrieval/answer, retrieved-context tokens, amortized extraction cost per candidate, and cost/token rollups by source, person, and domain. Unknown live-provider pricing stays `null` with `cost_status: "unknown"` instead of being reported as zero. Attribution groups are non-additive: if one event references multiple sources or domains, the same event is counted in each relevant group.

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

HTTP API routes require both the shared API token and an `actor` payload. Read the real local values from the ignored `var/config/settings.yaml` runtime config: `api.auth_token` for `X-Memco-Token`, and `api.actor_policies.dev-owner.auth_token` for the owner actor block. Do not commit those local token values.

```bash
curl -sS http://127.0.0.1:8788/v1/ingest/pipeline \
  -H 'Content-Type: application/json' \
  -H 'X-Memco-Token: replace-with-local-token' \
  -d '{
    "workspace": "default",
    "path": "/absolute/path/to/conversation.json",
    "source_type": "json",
    "person_display_name": "Alice",
    "person_slug": "alice",
    "aliases": ["Alice"],
    "actor": {
      "actor_id": "dev-owner",
      "actor_type": "owner",
      "auth_token": "from local ignored var/config/settings.yaml actor_policies",
      "can_view_sensitive": true
    }
  }'
```

If you prefer inline text instead of a file path:

```bash
curl -sS http://127.0.0.1:8788/v1/ingest/pipeline \
  -H 'Content-Type: application/json' \
  -H 'X-Memco-Token: replace-with-local-token' \
  -d '{
    "workspace": "default",
    "text": "Alice: I moved to Lisbon.",
    "source_type": "text",
    "title": "inline-seed",
    "actor": {
      "actor_id": "dev-owner",
      "actor_type": "owner",
      "auth_token": "from local ignored var/config/settings.yaml actor_policies",
      "can_view_sensitive": true
    }
  }'
```

For `ingest/pipeline`, `chat`, and `retrieve`, the API still requires an `actor` block even in private mode.

If you want narrower answer/retrieval surfaces for agents or operator tooling, `retrieve`, `chat`, and persona export now also accept a detail policy:

- `core_only`
- `balanced`
- `exhaustive`

Examples:

```bash
uv run memco retrieve "Where does Alice live?" alice --detail-policy core_only --root "$ROOT"
uv run memco chat "Where does Alice live?" alice --detail-policy core_only --root "$ROOT"
uv run memco persona-export --person-slug alice --detail-policy exhaustive --root "$ROOT"
```

On the HTTP side, the same contract is exposed through `detail_policy` in the JSON request body for `/v1/retrieve`, `/v1/chat`, and `/v1/persona/export`.

The quick repo-local release gate can be run locally with:

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

Both `release-check` entrypoints are intentionally fail-closed on incomplete live-provider config.
If `MEMCO_LLM_API_KEY` or the provider base URL is missing, expect `runtime_policy.ok = false` instead of a misleading green result.
The green repo-local artifacts under `var/reports/` come from the same commands run with live provider credentials injected into the local operator shell.

If you want the canonical Postgres gate instead of the quick local fallback path:

```bash
uv run memco release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'
```

That variant runs runtime policy, storage contract, operator safety, pytest, the acceptance artifact on Postgres, and the no-Docker API bootstrap smoke. It returns one combined JSON artifact for the canonical Postgres path.

To fold the live operator smoke into the same gate:

```bash
MEMCO_RUN_LIVE_SMOKE=1 \
MEMCO_API_TOKEN='replace-with-local-token' \
MEMCO_LLM_API_KEY='replace-with-provider-key' \
uv run memco release-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'
```

If you want the full benchmark-backed quality claim instead of an acceptance-only gate:

```bash
uv run memco strict-release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'
```

That strict variant keeps the canonical Postgres gate and adds the benchmark artifact with enforced quality thresholds.

For the release-grade claim, use the gate that requires canonical Postgres, benchmark thresholds, operator-readiness, and live operator smoke in one path:

```bash
MEMCO_RUN_LIVE_SMOKE=1 \
MEMCO_API_TOKEN='replace-with-local-token' \
MEMCO_LLM_API_KEY='replace-with-provider-key' \
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'
```

`release-check` and `strict-release-check` remain useful development/quality gates. They are not by themselves a final local private operator-controlled release claim when live smoke is skipped.

In this checkout, the latest persisted repo-local gate artifacts are typically kept under `var/reports/`, for example:

- `var/reports/release-check-current.json`
- `var/reports/release-check-postgres-current.json`
- `var/reports/strict-release-check-current.json`
- `var/reports/benchmark-current.json`
- `var/reports/live-operator-smoke-current.json`
- `var/reports/repo-local-status-current.json`
- `var/reports/change-groups-current.json`
- `var/reports/local-artifacts-refresh-current.json`
- `var/reports/local-artifacts-refresh-postgres-current.json`

To refresh those local operator artifacts in one step:

```bash
uv run memco local-artifacts-refresh --project-root /Users/martin/memco
```

If you also want to refresh the Postgres-smoke artifact in the same run:

```bash
uv run memco local-artifacts-refresh \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'
```

To persist the refresh summary itself:

```bash
uv run memco local-artifacts-refresh \
  --project-root /Users/martin/memco \
  --output /absolute/path/to/local-artifacts-refresh.json
```

## Recommended Runtime Paths

For this machine, the canonical storage contract is Postgres-first:

- PostgreSQL via any reachable Postgres instance
- versioned SQL migrations
- API running with `MEMCO_STORAGE_ENGINE=postgres`

SQLite remains available only as a local compatibility/dev fallback and should not be treated as the canonical storage contract.

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

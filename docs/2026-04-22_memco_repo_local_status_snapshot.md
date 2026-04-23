# Memco Repo-Local Status Snapshot

Date: 2026-04-22
Status: repo-local status snapshot

## Active Contract

Active repo-local contract status: `GO`

Controlling contract:

- [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md)

Separate reference-track status:

- strict original brief: `NO-GO`
- reference doc: [2026-04-22_memco_original_brief_status.md](2026-04-22_memco_original_brief_status.md)

## Fresh Baselines

Full suite:

- `uv run pytest -q` -> `321 passed in 9.57s`

Repo-local release gate:

- `uv run memco release-check --project-root /Users/martin/memco` -> `ok: true`
- pytest gate inside release-check -> `47 passed`
- acceptance artifact -> `27/27 passed`
- temporary acceptance root intentionally uses SQLite fallback when no local runtime config exists there

Contract-facing regression stack:

- `uv run pytest -q tests/test_docs_contract.py tests/test_release_check.py tests/test_cli_release_check.py tests/test_config.py tests/test_llm_provider.py` -> `74 passed in 4.45s`

Optional no-Docker Postgres variant:

- `uv run memco release-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'` -> `ok: true`
- postgres smoke -> `ok: true`
- `MEMCO_RUN_LIVE_SMOKE=1 ... uv run memco release-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'` -> `ok: true`
- operator safety gate -> `ok: true`
- live operator smoke -> `ok: true`

## Persisted Artifacts

- repo-local gate artifact:
  - `var/reports/release-check-current.json`
- repo-local gate + Postgres smoke artifact:
  - `var/reports/release-check-postgres-current.json`
- live operator smoke artifact:
  - `var/reports/live-operator-smoke-current.json`
- machine-readable local status snapshot:
  - `var/reports/repo-local-status-current.json`
  - mirrors the current branch, remote, contract split, and latest validation counts
- machine-readable change grouping snapshot:
  - `var/reports/change-groups-current.json`
- local artifact refresh summaries:
  - `var/reports/local-artifacts-refresh-current.json`
  - `var/reports/local-artifacts-refresh-postgres-current.json`

## Scope Notes

- The current repo-local ingestion contract supports:
  - `text`
  - `markdown`
  - `chat`
  - `json`
  - `csv`
  - `email`
  - `pdf`
- `WhatsApp` and `Telegram` remain roadmap/reference-track items, not current shipped ingestion support.

## Key Contract Additions Now Landed

- subject binding is fail-closed
- support level uses:
  - `supported`
  - `partial`
  - `unsupported`
  - `contradicted`
  - `ambiguous`
- false-premise detection covers:
  - location
  - relation
  - date
  - preference
  - event claims
- runtime extraction default is `openai-compatible`
- `mock` is explicit fixture/test fallback
- temporal model separates:
  - `observed_at`
  - `valid_from`
  - `valid_to`
  - `event_at`
- positive agent-facing answers return:
  - `fact_ids`
  - `evidence_ids`
- operator safety now requires:
  - non-empty API token
  - backup path present
- RU/EN mixed-language regressions are present
- pending-review exclusion is enforced as a hard eval gate
- detail policy exists with:
  - `core_only`
  - `balanced`
  - `exhaustive`

## Use This Doc For

- fastest repo-local status check
- handoff into the next implementation cycle
- avoiding accidental collapse of repo-local `GO` into strict-original `GO`
- canonical tracked status surface for the repo-local contract

Local-only operator artifact:

- `HANDOFF_NEXT_AGENT.md` is intentionally local and ignored by git
- this snapshot is the tracked status surface that should stay visible in normal repo history

## First Commands

```bash
cd /Users/martin/memco
uv run pytest -q
uv run memco release-check --project-root /Users/martin/memco
uv run memco local-artifacts-refresh --project-root /Users/martin/memco
```

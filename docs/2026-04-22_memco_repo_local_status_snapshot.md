Historical document. Not current verdict.
Current verdict: see docs/CURRENT_STATUS.md

# Memco Repo-Local Status Snapshot

Date: 2026-04-23
Last refreshed on `main`: `17e1a7d` (`Merge pull request #5 from MartinCampbell1/codex/memco-node24-native-actions`)
Status: repo-local status snapshot
Status note: historical repo-local status snapshot, not current release verdict.
Current verdict: see docs/CURRENT_STATUS.md. The active gate definition lives in docs/2026-04-21_memco_release_readiness_gate.md.
This snapshot records a prior operator environment; do not use its green claims as fresh proof without artifact freshness validation.

## Active Contract

Active repo-local contract status: `GO`

Scope: local/private/operator-controlled/review-gated persona memory. This snapshot must not be used as a universal memory substrate, fully autonomous production memory, or public SaaS readiness claim.

Controlling contract:

- [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md)

Separate reference-track status:

- strict original brief: `NO-GO`
- reference doc: [2026-04-22_memco_original_brief_status.md](2026-04-22_memco_original_brief_status.md)

## Fresh Baselines

Full suite:

- `uv run pytest -q` -> `347 passed`

Repo-local release gate:

- plain checkout shell without injected live provider creds:
  - `uv run memco release-check --project-root /Users/martin/memco` -> `ok: false`
  - `runtime_policy.reason` -> `openai-compatible provider is missing api_key`
- green operator path with live creds injected into the local shell:
  - saved artifact `var/reports/release-check-current.json` -> `ok: true`
  - pytest gate inside release-check -> `52 passed`
  - acceptance artifact -> `27/27 passed`
  - temporary acceptance root intentionally uses SQLite fallback when no local runtime config exists there
- release-grade claim:
  - `MEMCO_RUN_LIVE_SMOKE=1 ... uv run memco release-readiness-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'` -> `ok: true`
  - requires canonical Postgres, strict benchmark thresholds, operator-readiness pass rate, and live operator smoke

Contract-facing regression stack:

- `uv run pytest -q tests/test_docs_contract.py tests/test_release_check.py tests/test_cli_release_check.py tests/test_config.py tests/test_llm_provider.py` -> `87 passed`

Optional no-Docker Postgres variant:

- env-injected live operator path against local `codex-lb` (`http://127.0.0.1:2455/v1`):
  - `uv run memco release-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'` -> `ok: true`
- postgres smoke -> `ok: true`
- `MEMCO_RUN_LIVE_SMOKE=1 ... uv run memco release-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'` -> `ok: true`
- operator safety gate -> `ok: true`
- live operator smoke -> `ok: true`
- current tracked CI baseline on `main` uses Node 24-native GitHub Actions versions

## Persisted Artifacts

- repo-local gate artifact:
  - `var/reports/release-check-current.json`
- repo-local gate + Postgres smoke artifact:
  - `var/reports/release-check-postgres-current.json`
- live operator smoke artifact:
  - `var/reports/live-operator-smoke-current.json`
- artifact semantics:
  - release artifacts include generation timestamp, runtime mode, config source, env override state, live-smoke state, and checkout/config freshness context
  - historical artifacts without this context should be treated as legacy/unknown, not current release proof
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
MEMCO_RUN_LIVE_SMOKE=1 uv run memco release-readiness-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'
uv run memco local-artifacts-refresh --project-root /Users/martin/memco
```

Inject live provider env before expecting `release-check` to return `ok: true`.

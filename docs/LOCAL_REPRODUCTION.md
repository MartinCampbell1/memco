# Memco Local Reproduction

This runbook separates fixture confidence from release-grade proof. Fixture checks may use sqlite and mock/deterministic providers; release claims require the configured Postgres runtime plus live smoke.

## Setup

```bash
uv sync --extra dev --extra parsers
cp .env.example .env
set -a
source .env
set +a
```

Edit `.env` locally. Do not commit real credentials.

The live OpenAI-compatible path needs local values for:

```bash
export MEMCO_ROOT=/Users/martin/memco
export MEMCO_PROJECT_ROOT=/Users/martin/memco
export MEMCO_LLM_BASE_URL=http://127.0.0.1:2455/v1
export MEMCO_LLM_API_KEY=replace-with-local-provider-key
export MEMCO_API_TOKEN=replace-with-local-api-token
export MEMCO_OWNER_PERSON_SLUG=replace-with-owner-slug
export MEMCO_OWNER_DISPLAY_NAME='Replace With Owner Name'
```

Initialize the owner person before relying on owner-first-person fallback:

```bash
uv run memco person-upsert \
  --slug "$MEMCO_OWNER_PERSON_SLUG" \
  --display-name "$MEMCO_OWNER_DISPLAY_NAME" \
  --root "$MEMCO_ROOT"
```

## Preflight

```bash
uv run memco doctor --project-root .
```

`doctor` prints a redacted JSON report. It shows whether the repo-local config, backup path, personal-memory goldens, realistic goldens, owner settings, provider settings, and gate commands are present.

## Fixture Gates

These commands are useful for local regression work. They are not release-grade proof by themselves.

```bash
uv run pytest -q
uv run pytest tests/test_private_agent_semantic_regressions.py -q
uv run memco eval personal-memory \
  --goldens eval/personal_memory_goldens \
  --output var/reports/personal-memory-eval-current.json
uv run memco release-check \
  --project-root . \
  --fixture-ok \
  --include-realistic-eval \
  --output var/reports/release-check-fixture-current.json
```

The realistic personal-memory file is `eval/personal_memory_goldens/realistic_personal_memory_goldens.jsonl`. The `--fixture-ok` artifact is archive-safe by construction: it reports `fixture_only: true` and `release_eligible: false`.

The personal-memory eval artifact also includes `long_corpus_stress`: an internal synthetic JSON stress smoke with extraction token accounting, candidate volume, fact growth, retrieval latency, false-positive retrieval checks, and refusal-quality probes. Its `p2_3_target_report` keeps full P2.3 `ok_for_full_p2_3_claim=false` until 50k/500k-message and mixed-source stress are actually run; it is not paper-equivalent proof.

The artifact also includes `p2_1_external_benchmark_report`: public/external LoCoMO remains `not_run`, and `ok_for_pdf_score_claim=false` until a real external benchmark and judge protocol are executed.

For an experience timeline smoke after seeding and publishing event facts:

```bash
uv run memco build-life-timeline alice --root "$MEMCO_ROOT"
```

## Current Status Consistency

After a fresh pytest run or artifact refresh, verify that `docs/CURRENT_STATUS.md` does not over-claim stale evidence:

```bash
uv run memco verify-current-status --project-root . --pytest-passed <fresh-pytest-passed-count>
```

This command fail-closes when the documented pytest count differs from the fresh count, when required current artifacts are missing, or when `var/reports/*current*.json` artifacts are stale relative to the current checkout/config/env.

## Postgres And Live Gates

Use a local environment variable for the maintenance URL. The command output redacts runtime context, but the shell variable itself is secret-bearing.

```bash
export MEMCO_POSTGRES_DATABASE_URL='postgresql://user:password@127.0.0.1:5432/postgres'

uv run memco release-check \
  --project-root . \
  --postgres-database-url "$MEMCO_POSTGRES_DATABASE_URL" \
  --include-realistic-eval \
  --output var/reports/release-check-postgres-current.json

MEMCO_RUN_LIVE_SMOKE=1 uv run memco release-readiness-check \
  --project-root . \
  --postgres-database-url "$MEMCO_POSTGRES_DATABASE_URL" \
  --require-live-provider \
  --require-postgres \
  --output var/reports/release-readiness-check-current.json
```

Only the final `release-readiness-check` path supports a release-grade claim because it requires canonical Postgres, strict benchmark thresholds, and live operator smoke.

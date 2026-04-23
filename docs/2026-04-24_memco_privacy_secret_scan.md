# Memco Privacy And Secret Scan Note

Date: 2026-04-24
Status: historical pre-remediation privacy scan, not current release verdict.
Current release verdict lives in `docs/2026-04-24_memco_release_closure.md`.
Audit package index: `docs/2026-04-24_memco_audit_package_index.md`

## Purpose

This note records a lightweight secret/privacy scan performed as part of the 2026-04-24 pre-remediation audit package.

It is not a full public-release safety audit. The current product is private/single-user, but local memory systems still need careful secret handling.

## Commands

High-signal secret pattern scan:

```bash
rg -n --hidden \
  --glob '!*.pdf' \
  --glob '!var/**' \
  --glob '!.git/**' \
  --glob '!node_modules/**' \
  --glob '!.venv/**' \
  "(sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]+|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]+|postgresql://[^\\s'\\\"]+:[^\\s'\\\"]+@)" \
  .
```

Tracked sensitive-file check:

```bash
git ls-files .env .env.local var/config/settings.yaml var/reports/release-readiness-check-current.json .omc/state/hud-stdin-cache.json docker-compose.yml .env.example
```

Ignore check:

```bash
git check-ignore -v var/config/settings.yaml var/reports/release-readiness-check-current.json .env .env.local || true
```

## Findings

### No high-confidence live provider keys found in tracked files

The scan did not find obvious OpenAI-style `sk-...`, GitHub PAT, Slack token, or similar live API secret patterns in tracked files.

Most hits were:

- placeholders such as `replace-with-provider-key`
- test values such as `secret`
- field names like `api_key`, `auth_token`, and `token_count`
- example Postgres URLs using `memco:memco`

### Tracked files with intentional placeholder credentials

Tracked files:

```text
.env.example
docker-compose.yml
```

Notes:

- `.env.example` contains placeholders, not live credentials.
- `docker-compose.yml` contains `memco:memco` demo Postgres credentials. This is acceptable as a local/demo Docker example, but not as production-secret material.

### Local runtime config is ignored

Relevant `.gitignore` lines:

```text
.env
var/
```

Observed:

```text
var/config/settings.yaml exists locally
var/config/settings.yaml is ignored by var/
```

This is correct for local runtime secrets/config, but it also means release claims must explicitly distinguish local ignored config from tracked source.

### `.env.local` is not explicitly ignored

The repo ignores `.env`, but not `.env.local` specifically.

There was no `.env.local` present in the current check. Still, if future operators use `.env.local`, it should be added to `.gitignore` or avoided.

### `.omc/` is untracked local state

Current `git status` includes:

```text
?? .omc/
```

The scan saw local `.omc/state/hud-stdin-cache.json` content containing session/runtime metadata. It did not look like an API key, but it is local operator state and should not be committed or published.

## Privacy/Safety Implications

This scan did not change the pre-remediation audit verdict:

```text
NO-GO for honest private Hermes/API-backed use until P0 blockers are fixed and fresh release-readiness proof is produced.
```

For the current remediated private-release verdict, use `docs/2026-04-24_memco_release_closure.md`.

It does add these safety requirements before any public/private handoff claim:

1. Do not commit `.omc/`.
2. Do not commit `var/`.
3. Do not commit real `.env` files.
4. Consider ignoring `.env.*` if operators may use `.env.local`.
5. Keep generated actor credentials in ignored local config or a local secret store.
6. Keep audit docs using placeholders for provider and actor secrets.

## Public-Safety Note

This scan is not enough to declare the repository public-safe.

Before making the repo public, run a broader history and privacy audit:

- tracked file secret scan
- git history secret scan
- local docs privacy scan
- examples/default credentials review
- generated artifact review
- `.omc/`, `var/`, `.env*`, and local report exclusion check

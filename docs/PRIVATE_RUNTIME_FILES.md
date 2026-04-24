# Private Runtime Files

Status: active operator hygiene rule for local/private Memco work.

Memco runtime state is private user memory plus local operator credentials. Do not send these files to agents, reviewers, issue trackers, public repos, or audit archives:

- `var/config/**`
- `var/db/**`
- `var/backups/**`
- `var/log/**`
- `var/raw/**`
- `var/reports/**`
- `.env` and `.env.*`
- `.omc/**`
- local zip archives created from the repo or runtime

Use the sanitized audit package tooling when sharing source for review:

```bash
uv run python scripts/sanitize_release_archive.py --output /tmp/memco_safe.zip
uv run python scripts/scan_archive_for_secrets.py /tmp/memco_safe.zip
```

Expected scanner result:

```text
no secrets found
no forbidden runtime paths found
```

If a previously shared archive included `var/config/settings.yaml`, API auth tokens, actor tokens, provider keys, database dumps, raw user data, or LLM usage logs, rotate those secrets in the provider/database/operator systems. The repository can enforce future hygiene, but it cannot rotate already exposed external credentials.

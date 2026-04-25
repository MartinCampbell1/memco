# Backup And Restore Runbook

Current scope: private single-user local operation. Stop Memco writers before native restore commands, keep a pre-restore copy of the current database, and verify every backup before treating it as usable.

## SQLite Mode

Create a native SQLite backup:

```bash
sqlite3 var/db/memco.db ".backup 'var/backups/memco-sqlite.backup'"
```

Run the SQLite corruption check:

```bash
sqlite3 var/db/memco.db "PRAGMA integrity_check;"
```

Restore from the native SQLite backup after stopping writers:

```bash
cp var/backups/memco-sqlite.backup var/db/memco.db
```

## Postgres Mode

Create a Postgres custom-format dump:

```bash
pg_dump "$MEMCO_POSTGRES_DATABASE_URL" --format=custom --file var/backups/memco-postgres.dump
```

Check that the dump is readable before relying on it:

```bash
pg_restore --list var/backups/memco-postgres.dump
```

Restore to the selected target database after confirming the target:

```bash
pg_restore --clean --if-exists --no-owner --dbname "$MEMCO_POSTGRES_DATABASE_URL" var/backups/memco-postgres.dump
```

## JSON Exports

Use audit exports for redacted review bundles, not restore:

```bash
uv run memco backup export --mode audit --output var/backups/memco-audit-export.json --root "$ROOT"
uv run memco backup verify var/backups/memco-audit-export.json
```

Use encrypted full exports for private restore validation:

```bash
MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup export --mode full --encrypted --output var/backups/memco-full-backup.json.enc --root "$ROOT"
MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup verify var/backups/memco-full-backup.json.enc
MEMCO_BACKUP_PASSPHRASE='replace-with-local-passphrase' uv run memco backup restore-dry-run var/backups/memco-full-backup.json.enc
```

## Generated Command Checklist

The CLI can print the engine-specific checklist for the current root:

```bash
uv run memco backup runbook --root "$ROOT"
uv run memco backup runbook --storage-engine postgres --root "$ROOT"
```

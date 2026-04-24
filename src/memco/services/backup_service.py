from __future__ import annotations

import base64
import json
from json import JSONDecodeError
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from memco.db import POSTGRES_BASE_VERSION, SQLITE_BASE_VERSION
from memco.utils import isoformat_z


REQUIRED_BACKUP_TABLES = {
    "workspaces",
    "persons",
    "memory_facts",
    "memory_evidence",
    "schema_migrations",
}
AUDIT_REDACTED_COLUMNS = {
    ("sources", "parsed_text"),
    ("source_chunks", "text"),
    ("conversation_messages", "text"),
    ("conversation_chunks", "text"),
    ("source_segments", "text"),
    ("memory_evidence", "quote_text"),
}
AUDIT_JSON_COLUMNS = {
    ("fact_candidates", "evidence_json"),
    ("review_queue", "candidate_json"),
}
AUDIT_REDACTED_JSON_KEYS = {
    "quote",
    "quote_text",
    "text",
    "parsed_text",
    "raw_text",
}
BACKUP_KDF_ITERATIONS = 390_000


class BackupService:
    format_version = 1

    def export_backup(
        self,
        conn,
        *,
        output_path: Path,
        storage_engine: str,
        mode: str = "audit",
        encrypted: bool = False,
        passphrase: str | None = None,
    ) -> dict:
        normalized_mode = self._normalize_mode(mode)
        payload = self._build_payload(conn, storage_engine=storage_engine, mode=normalized_mode)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if encrypted:
            if not passphrase:
                raise ValueError("Encrypted backup export requires a passphrase.")
            artifact = self._encrypt_payload(payload, passphrase=passphrase)
        else:
            artifact = payload
        output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        verification = self.verify_payload(payload)
        return {
            "artifact_type": "backup_export_summary",
            "ok": verification["ok"],
            "backup_path": str(output_path),
            "mode": normalized_mode,
            "encrypted": encrypted,
            "format_version": self.format_version,
            "table_counts": payload["table_counts"],
            "migration_compatibility": verification["migration_compatibility"],
        }

    def verify_backup(self, backup_path: Path, *, passphrase: str | None = None) -> dict:
        payload, encrypted = self._load_payload(backup_path, passphrase=passphrase)
        verification = self.verify_payload(payload)
        return {
            "artifact_type": "backup_verify",
            "backup_path": str(backup_path),
            "encrypted": encrypted,
            **verification,
        }

    def is_encrypted_backup(self, backup_path: Path) -> bool:
        artifact = self._read_json_file(backup_path)
        return bool(artifact.get("encrypted"))

    def restore_dry_run(self, backup_path: Path, *, passphrase: str | None = None) -> dict:
        payload, encrypted = self._load_payload(backup_path, passphrase=passphrase)
        verification = self.verify_payload(payload)
        restorable = payload.get("mode") == "full" and not payload.get("sanitized", False)
        return {
            "artifact_type": "backup_restore_dry_run",
            "backup_path": str(backup_path),
            "encrypted": encrypted,
            "ok": bool(verification["ok"] and restorable),
            "would_write": False,
            "restorable": restorable,
            "reason": "" if restorable else "Only full non-sanitized backups are restorable.",
            "table_counts": payload.get("table_counts", {}),
            "migration_compatibility": verification["migration_compatibility"],
            "required_table_checks": verification["required_table_checks"],
        }

    def verify_payload(self, payload: dict[str, Any]) -> dict:
        table_counts = payload.get("table_counts") or {}
        required_table_checks = {
            table: {
                "present": table in table_counts,
                "row_count": int(table_counts.get(table, 0)) if table in table_counts else 0,
            }
            for table in sorted(REQUIRED_BACKUP_TABLES)
        }
        migration_compatibility = self._migration_compatibility(payload)
        ok = (
            payload.get("artifact_type") == "memco_backup_export"
            and payload.get("format_version") == self.format_version
            and all(item["present"] for item in required_table_checks.values())
            and migration_compatibility["compatible"]
        )
        return {
            "ok": ok,
            "format_version": payload.get("format_version"),
            "mode": payload.get("mode"),
            "sanitized": bool(payload.get("sanitized", False)),
            "storage_engine": payload.get("storage_engine", ""),
            "table_counts": table_counts,
            "required_table_checks": required_table_checks,
            "migration_compatibility": migration_compatibility,
        }

    def _build_payload(self, conn, *, storage_engine: str, mode: str) -> dict[str, Any]:
        tables: dict[str, list[dict[str, Any]]] = {}
        for table_name in self._table_names(conn):
            tables[table_name] = self._table_rows(conn, table_name=table_name, mode=mode)
        schema_migrations = [
            str(row.get("version") or "")
            for row in tables.get("schema_migrations", [])
            if row.get("version")
        ]
        return {
            "artifact_type": "memco_backup_export",
            "format_version": self.format_version,
            "mode": mode,
            "sanitized": mode == "audit",
            "encrypted": False,
            "exported_at": isoformat_z(),
            "storage_engine": storage_engine,
            "schema_migrations": sorted(schema_migrations),
            "table_counts": {table: len(rows) for table, rows in sorted(tables.items())},
            "tables": tables,
        }

    def _table_names(self, conn) -> list[str]:
        if self._is_postgres(conn):
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
            return [str(row["table_name"]) for row in rows]
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()
        names = [str(row["name"]) for row in rows]
        return [
            name
            for name in names
            if not name.startswith("sqlite_") and "_fts" not in name
        ]

    def _table_rows(self, conn, *, table_name: str, mode: str) -> list[dict[str, Any]]:
        quoted = self._quote_identifier(table_name)
        rows = conn.execute(f"SELECT * FROM {quoted} ORDER BY 1").fetchall()
        return [
            {
                key: self._json_safe_value(
                    self._sanitize_value(table_name=table_name, column_name=key, value=value, mode=mode)
                )
                for key, value in dict(row).items()
            }
            for row in rows
        ]

    def _sanitize_value(self, *, table_name: str, column_name: str, value: Any, mode: str) -> Any:
        if mode != "audit":
            return value
        if (table_name, column_name) in AUDIT_REDACTED_COLUMNS:
            return self._redacted_text_value(value)
        if (table_name, column_name) in AUDIT_JSON_COLUMNS:
            return self._sanitize_json_blob(value)
        return value

    def _redacted_text_value(self, value: Any) -> dict:
        text = "" if value is None else str(value)
        return {
            "redacted": True,
            "original_length": len(text),
        }

    def _sanitize_json_blob(self, value: Any) -> Any:
        if value in {None, ""}:
            return value
        try:
            parsed = json.loads(str(value))
        except JSONDecodeError:
            return self._redacted_text_value(value)
        return self._redact_json_value(parsed)

    def _redact_json_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._redact_json_value(item) for item in value]
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                if str(key) in AUDIT_REDACTED_JSON_KEYS:
                    redacted[key] = self._redacted_text_value(item)
                else:
                    redacted[key] = self._redact_json_value(item)
            return redacted
        return value

    def _json_safe_value(self, value: Any) -> Any:
        if isinstance(value, bytes):
            return {
                "encoding": "base64",
                "value": base64.b64encode(value).decode("ascii"),
            }
        return value

    def _migration_compatibility(self, payload: dict[str, Any]) -> dict:
        storage_engine = str(payload.get("storage_engine") or "")
        expected = POSTGRES_BASE_VERSION if storage_engine == "postgres" else SQLITE_BASE_VERSION
        versions = sorted(str(item) for item in payload.get("schema_migrations", []))
        return {
            "compatible": expected in versions,
            "expected_base_migration": expected,
            "schema_migrations": versions,
        }

    def _encrypt_payload(self, payload: dict[str, Any], *, passphrase: str) -> dict:
        salt = secrets.token_bytes(16)
        key = self._derive_key(passphrase=passphrase, salt=salt)
        token = Fernet(key).encrypt(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return {
            "artifact_type": "memco_backup_export_encrypted",
            "format_version": self.format_version,
            "encrypted": True,
            "cipher": "fernet",
            "kdf": "pbkdf2_hmac_sha256",
            "iterations": BACKUP_KDF_ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "payload": token.decode("ascii"),
        }

    def _load_payload(self, backup_path: Path, *, passphrase: str | None) -> tuple[dict[str, Any], bool]:
        artifact = self._read_json_file(backup_path)
        if not artifact.get("encrypted"):
            return artifact, False
        if not passphrase:
            raise ValueError("Encrypted backup verification requires a passphrase.")
        try:
            salt = base64.b64decode(str(artifact["salt"]).encode("ascii"))
            key = self._derive_key(passphrase=passphrase, salt=salt)
            raw_payload = Fernet(key).decrypt(str(artifact["payload"]).encode("ascii"))
        except (InvalidToken, KeyError, ValueError) as exc:
            raise ValueError("Encrypted backup could not be decrypted.") from exc
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except JSONDecodeError as exc:
            raise ValueError("Encrypted backup payload is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Encrypted backup payload must contain a JSON object.")
        return payload, True

    def _read_json_file(self, backup_path: Path) -> dict[str, Any]:
        try:
            artifact = json.loads(backup_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Backup file could not be read: {backup_path}") from exc
        except JSONDecodeError as exc:
            raise ValueError("Backup file is not valid JSON.") from exc
        if not isinstance(artifact, dict):
            raise ValueError("Backup file must contain a JSON object.")
        return artifact

    def _derive_key(self, *, passphrase: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=BACKUP_KDF_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))

    def _normalize_mode(self, mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized not in {"audit", "full"}:
            raise ValueError("Backup mode must be 'audit' or 'full'.")
        return normalized

    def _quote_identifier(self, value: str) -> str:
        if not value.replace("_", "").isalnum():
            raise ValueError(f"Unsafe table name: {value}")
        return f'"{value}"'

    def _is_postgres(self, conn) -> bool:
        return getattr(conn, "engine", "sqlite") == "postgres"

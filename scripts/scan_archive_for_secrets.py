#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
from pathlib import PurePosixPath
from zipfile import ZipFile


FORBIDDEN_PREFIXES = (
    ".git/",
    ".omc/",
    "var/",
)
FORBIDDEN_EXACT = {
    ".env",
    ".env.local",
    "var/config/settings.yaml",
}
SECRET_PATTERNS = (
    ("openai_style_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github_classic_pat", re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "long_actor_or_auth_token",
        re.compile(r"(?i)\b(?:actor_token|auth_token|api_token)\b\s*[:=]\s*[\"']([A-Za-z0-9._~+/=-]{32,})[\"']"),
    ),
    (
        "credentialed_postgres_url",
        re.compile(r"\bpostgres(?:ql)?://([^:\s/'\"]+):([^@\s/'\"]+)@([^\s'\"`]+)"),
    ),
)
ALLOWLIST_VALUES = {
    "example",
    "example-token",
    "fixture",
    "memco",
    "memco-token",
    "password",
    "replace-with-local-token",
    "replace-with-provider-key",
    "secret",
    "test",
    "user",
}


def _is_allowed_match(pattern_name: str, match: re.Match[str]) -> bool:
    text = match.group(0).lower()
    if pattern_name == "credentialed_postgres_url":
        user = match.group(1).lower()
        password = match.group(2).lower()
        return user in ALLOWLIST_VALUES and password in ALLOWLIST_VALUES
    return any(value in text for value in ALLOWLIST_VALUES)


def scan_archive(path: str) -> dict:
    findings: list[dict] = []
    with ZipFile(path) as archive:
        for member in archive.infolist():
            member_name = PurePosixPath(member.filename).as_posix()
            if member.is_dir():
                continue
            if member_name in FORBIDDEN_EXACT or any(member_name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                findings.append({"type": "forbidden_path", "path": member_name})
                continue
            data = archive.read(member)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for pattern_name, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    if _is_allowed_match(pattern_name, match):
                        continue
                    findings.append(
                        {
                            "type": "secret_pattern",
                            "pattern": pattern_name,
                            "path": member_name,
                        }
                    )

    return {
        "ok": not findings,
        "archive": path,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a Memco audit package for runtime data and likely secrets.")
    parser.add_argument("archive", help="Zip archive to scan.")
    args = parser.parse_args()

    result = scan_archive(args.archive)
    if result["ok"]:
        print("no secrets found")
        print("no forbidden runtime paths found")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

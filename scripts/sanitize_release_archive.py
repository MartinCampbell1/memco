#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SAFE_ROOTS = {"src", "tests", "docs", "scripts"}
SAFE_ROOT_FILES = {
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "IMPLEMENTATION_NOTES.md",
    "Makefile",
    "README.md",
    "docker-compose.yml",
    "pyproject.toml",
    "uv.lock",
}
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".omc",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "htmlcov",
    "node_modules",
    "var",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".dump", ".sqlite", ".sqlite3", ".zip"}
EXCLUDED_FILENAMES = {".DS_Store", "HANDOFF_NEXT_AGENT.md", "plan.md", "table.md"}


def _is_safe_member(relative_path: Path) -> bool:
    parts = relative_path.parts
    if not parts:
        return False
    if relative_path.name in EXCLUDED_FILENAMES:
        return False
    if any(part in EXCLUDED_PARTS for part in parts):
        return False
    if relative_path.suffix in EXCLUDED_SUFFIXES:
        return False
    if len(parts) == 1:
        return relative_path.name in SAFE_ROOT_FILES
    return parts[0] in SAFE_ROOTS


def build_archive(*, root: Path, output: Path) -> dict:
    root = root.resolve()
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    included: list[str] = []
    skipped: list[str] = []
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.resolve() == output:
                continue
            relative_path = path.relative_to(root)
            member_name = relative_path.as_posix()
            if not _is_safe_member(relative_path):
                skipped.append(member_name)
                continue
            archive.write(path, member_name)
            included.append(member_name)

    return {
        "ok": True,
        "root": str(root),
        "output": str(output),
        "included_count": len(included),
        "skipped_count": len(skipped),
        "included": included,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a sanitized Memco audit package.")
    parser.add_argument("--root", default=".", help="Memco repo root. Defaults to current directory.")
    parser.add_argument("--output", required=True, help="Output zip path.")
    args = parser.parse_args()

    result = build_archive(root=Path(args.root), output=Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

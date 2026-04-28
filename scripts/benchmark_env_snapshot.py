from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from memco.config import load_settings


def _git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _memco_version() -> str:
    try:
        return version("memco")
    except PackageNotFoundError:
        from memco import __version__

        return __version__


def build_environment_snapshot(project_root: Path) -> dict:
    settings = load_settings(project_root)
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "git_commit": _git_commit(project_root),
        "memco_version": _memco_version(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "answer_model": settings.llm.model,
        "judge_model": settings.llm.model,
        "embedding_model": "not_configured",
        "notes": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a Memco benchmark environment snapshot.")
    parser.add_argument("--project-root", default=".", help="Memco project root.")
    parser.add_argument(
        "--output",
        default="var/reports/benchmark-current/environment.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = project_root / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = build_environment_snapshot(project_root)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

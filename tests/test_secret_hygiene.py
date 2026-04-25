from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed_runtime_files(root: Path) -> None:
    (root / "src" / "memco").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "scripts").mkdir()
    (root / "README.md").write_text("# Memco\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'memco'\n", encoding="utf-8")
    (root / "src" / "memco" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_sample.py").write_text("def test_sample():\n    assert True\n", encoding="utf-8")
    (root / "docs" / "note.md").write_text("safe docs\n", encoding="utf-8")
    (root / "var" / "config").mkdir(parents=True)
    (root / "var" / "db").mkdir(parents=True)
    (root / "var" / "backups").mkdir(parents=True)
    (root / "var" / "log").mkdir(parents=True)
    (root / "var" / "raw").mkdir(parents=True)
    (root / "var" / "reports").mkdir(parents=True)
    (root / "var" / "config" / "settings.yaml").write_text("api_key: sk-live-secret-secret-secret\n", encoding="utf-8")
    (root / "var" / "db" / "memco.db").write_bytes(b"sqlite")
    (root / "var" / "backups" / "memco-postgres.dump").write_bytes(b"dump")
    (root / "var" / "log" / "llm_usage.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "var" / "raw" / "memory.md").write_text("private memory\n", encoding="utf-8")
    (root / "var" / "reports" / "release.json").write_text("{}\n", encoding="utf-8")


def test_sanitized_archive_excludes_runtime_files_and_scans_clean(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _seed_runtime_files(root)
    output = tmp_path / "memco_safe.zip"

    sanitize = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sanitize_release_archive.py"),
            "--root",
            str(root),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert sanitize.returncode == 0, sanitize.stderr
    with ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "src/memco/__init__.py" in names
    assert "tests/test_sample.py" in names
    assert "docs/note.md" in names
    assert "var/config/settings.yaml" not in names
    assert "var/db/memco.db" not in names
    assert "var/backups/memco-postgres.dump" not in names
    assert "var/log/llm_usage.jsonl" not in names
    assert not any(name.startswith("var/") for name in names)

    scan = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scan_archive_for_secrets.py"), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert scan.returncode == 0, scan.stdout
    assert "no secrets found" in scan.stdout


def test_archive_scanner_rejects_runtime_paths_and_live_keys(tmp_path):
    output = tmp_path / "unsafe.zip"
    fake_key = "sk-" + "A" * 32
    with ZipFile(output, "w") as archive:
        archive.writestr("var/config/settings.yaml", f"api_key: {fake_key}\n")
        archive.writestr("src/memco/example.py", f"TOKEN = '{fake_key}'\n")

    scan = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scan_archive_for_secrets.py"), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert scan.returncode == 1
    assert "forbidden_path" in scan.stdout
    assert "openai_style_api_key" in scan.stdout


def test_current_repo_sanitized_archive_scans_clean(tmp_path):
    output = tmp_path / "memco_repo_safe.zip"

    sanitize = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sanitize_release_archive.py"),
            "--root",
            str(REPO_ROOT),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert sanitize.returncode == 0, sanitize.stderr
    scan = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scan_archive_for_secrets.py"), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert scan.returncode == 0, scan.stdout
    assert "no secrets found" in scan.stdout
    assert "no forbidden runtime paths found" in scan.stdout

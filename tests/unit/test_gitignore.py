"""TD-2 (module-08 task 3.1.9; DL-38, DL-40): .gitignore holds the Python entries this repository
uses, nothing from the former Node.js template, and keeps .env out of every commit."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINES = [line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()]
ENTRIES = [line for line in LINES if line and not line.startswith("#")]

REQUIRED = [".env*", "!.env.example", ".import_linter_cache/", "__pycache__/", ".venv/", ".pytest_cache/"]
FOREIGN = [
    "node_modules", ".pnp", ".yarn", ".next", "/out", "next-env", "vercel", "npm-debug", "yarn-",
    "pnpm", "tsbuildinfo", "/scripts", "/roadmap", "/doc", "db/scripts", "*.jwt", "ca/", "spec-pipeline",
    "/pgdata", "/logs", "archive/", "sa-key", "/coverage", "/build",
]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def test_required_entries_are_present() -> None:
    assert [entry for entry in REQUIRED if entry not in ENTRIES] == []


def test_no_entry_from_the_former_template() -> None:
    assert [e for e in ENTRIES if any(f in e for f in FOREIGN)] == []


def test_no_tracked_file_is_ignored() -> None:
    tracked = _git("ls-files").stdout.split()
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"], cwd=ROOT, input="\n".join(tracked),
        capture_output=True, text=True,
    )
    assert result.stdout.split() == []


def test_env_is_ignored_and_cannot_be_added(tmp_path: Path) -> None:
    assert _git("check-ignore", "-q", "--no-index", ".env").returncode == 0
    assert _git("check-ignore", "-q", "--no-index", ".env.local").returncode == 0
    assert _git("check-ignore", "-q", "--no-index", ".env.example").returncode == 1
    assert _git("add", "--dry-run", ".env").returncode != 0

"""README (module-09 task 3.1.1): it documents run and test with what the repository actually
uses, and cannot drift from CLAUDE.md, .env.example, TDD sections 6.1 and 7 or the code."""

import re
from pathlib import Path

import pytest

from app.billing.service import REASON_CODES

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()


def _claude_commands() -> list[str]:
    claude = (ROOT / "CLAUDE.md").read_text()
    after_heading = claude.split("\nCOMMANDS\n", 1)[1].split("\n", 1)[1]  # skip the ==== line
    section = after_heading.split("\n====", 1)[0]
    return [c for c in re.findall(r"`([^`]+)`", section) if c.startswith(("uv ", "docker "))]


def _env_keys() -> list[str]:
    lines = (ROOT / ".env.example").read_text().splitlines()
    return [line.split("=", 1)[0] for line in lines if line and not line.startswith("#")]


def _endpoints() -> list[str]:
    tdd = (ROOT / "docs/TDD.md").read_text()
    section = tdd.split("### 6.1 Endpoints", 1)[1].split("Success responses", 1)[0]
    return re.findall(r"^\| `((?:GET|POST) [^`]+)`", section, flags=re.MULTILINE)


@pytest.mark.parametrize("command", _claude_commands())
def test_every_claude_md_command_is_documented(command: str) -> None:
    assert command in README


def test_the_command_list_is_not_empty() -> None:
    assert len(_claude_commands()) >= 8


@pytest.mark.parametrize("key", _env_keys())
def test_every_env_example_key_is_documented(key: str) -> None:
    assert key in README


def test_setup_copies_the_env_example() -> None:
    assert "cp .env.example .env" in README


@pytest.mark.parametrize("endpoint", _endpoints())
def test_every_endpoint_is_documented(endpoint: str) -> None:
    assert endpoint in README


@pytest.mark.parametrize("code", sorted(REASON_CODES))
def test_every_failure_reason_code_is_documented(code: str) -> None:
    assert f"`{code}`" in README


@pytest.mark.parametrize("queue", ["billing.parking", "visits.parking"])
def test_parking_queues_are_documented(queue: str) -> None:
    assert queue in README


@pytest.mark.parametrize(
    "link", ["docs/PRD.md", "docs/TDD.md", "docs/HANDOFF.md", "docs/build-spec/"]
)
def test_the_design_documents_are_linked(link: str) -> None:
    assert f"]({link}" in README


def test_no_em_or_en_dash() -> None:
    assert "—" not in README and "–" not in README


def test_no_literal_credential() -> None:
    assert not re.search(r"\b(postgres|guest|visits_app|billing_app|jiris_migrator):\1@", README)
    assert not re.search(r"(PASSWORD|_USER)=\S", README)

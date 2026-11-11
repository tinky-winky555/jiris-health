"""Rule for every consumer (module-05 section 3; contract DL-21): queue objects come only from
app/outbox/topology.py; module code declares no queue and binds none."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_SOURCES = sorted(
    path for module in ("billing", "visits") for path in (ROOT / "app" / module).rglob("*.py")
)
FORBIDDEN = [
    (re.compile(r"\bRabbitQueue\s*\("), "constructs a RabbitQueue"),
    (re.compile(r"\bdeclare_queue\b"), "declares a queue"),
    (re.compile(r"\bRabbitExchange\s*\("), "constructs a RabbitExchange"),
    (re.compile(r"subscriber\s*\([^)]*\bexchange\s*="), "binds a subscriber to an exchange"),
    (re.compile(r"\.bind\s*\("), "binds a queue"),
]


def test_module_sources_are_found() -> None:
    assert any(path.name == "consumer.py" for path in MODULE_SOURCES)


@pytest.mark.parametrize("path", MODULE_SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_module_code_declares_and_binds_no_queue(path: Path) -> None:
    source = path.read_text()
    found = [reason for pattern, reason in FORBIDDEN if pattern.search(source)]
    assert found == [], f"{path.relative_to(ROOT)}: {', '.join(found)}"


def test_billing_consumer_takes_its_queue_from_the_topology() -> None:
    source = (ROOT / "app/billing/consumer.py").read_text()
    assert "from app.outbox.topology import" in source
    assert "INBOX_QUEUES[BILLING_INBOX]" in source

"""Both Alembic chains apply from empty (session fixture) and match the models."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.helpers import Stack

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("chain", ["visits", "billing"])
def test_models_match_migrations(stack: Stack, chain: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-n", chain, "check"],
        cwd=ROOT,
        env={**os.environ, **stack.env},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

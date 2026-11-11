"""Compose configuration (module-08 tasks 3.1.4 and 3.1.10; DL-38, DL-41): rendered by
`docker compose config` with throwaway values, as a developer's .env would provide them."""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
VARIABLES = (
    "POSTGRES_PASSWORD",
    "JIRIS_MIGRATOR_PASSWORD",
    "VISITS_APP_PASSWORD",
    "BILLING_APP_PASSWORD",
    "RABBITMQ_USER",
    "RABBITMQ_PASSWORD",
)


def _config(env: dict[str, str]) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    return subprocess.run(
        ["docker", "compose", "--env-file", os.devnull, "config", "--format", "json"],
        cwd=ROOT,
        env={**clean, **env},
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def services() -> dict:
    result = _config({name: f"test-{name.lower()}" for name in VARIABLES})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


def test_compose_refuses_to_start_without_the_credentials() -> None:
    result = _config({})
    assert result.returncode != 0
    assert "required" in result.stderr.lower() or "must be set" in result.stderr.lower(), result.stderr


def test_migrate_receives_only_the_migration_url(services: dict) -> None:
    assert set(services["migrate"]["environment"]) == {"MIGRATIONS_DATABASE_URL"}


def test_api_receives_the_two_module_urls_only(services: dict) -> None:
    assert set(services["api"]["environment"]) == {"VISITS_DATABASE_URL", "BILLING_DATABASE_URL"}


def test_worker_receives_module_urls_and_the_broker(services: dict) -> None:
    assert set(services["worker"]["environment"]) == {
        "VISITS_DATABASE_URL",
        "BILLING_DATABASE_URL",
        "RABBITMQ_URL",
    }


@pytest.mark.parametrize("service", ["api", "worker"])
def test_api_and_worker_have_a_restart_policy(services: dict, service: str) -> None:
    assert services[service].get("restart") == "unless-stopped"


def test_credentials_reach_the_services(services: dict) -> None:
    assert "test-visits_app_password" in services["worker"]["environment"]["VISITS_DATABASE_URL"]
    assert services["rabbitmq"]["environment"]["RABBITMQ_DEFAULT_PASS"] == "test-rabbitmq_password"
    assert services["postgres"]["environment"]["JIRIS_MIGRATOR_PASSWORD"] == "test-jiris_migrator_password"

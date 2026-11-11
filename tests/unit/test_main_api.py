"""The API process reads the two module database URLs, one pool per role (D13; contract DL-24),
and never the migration role or the broker."""

import logging

import pytest

from app.main_api import create_app

VISITS_URL = "postgresql+asyncpg://visits_app:x@localhost/jiris"
BILLING_URL = "postgresql+asyncpg://billing_app:x@localhost/jiris"
OTHER_SETTINGS = ("MIGRATIONS_DATABASE_URL", "RABBITMQ_URL")


@pytest.mark.parametrize("missing", ["VISITS_DATABASE_URL", "BILLING_DATABASE_URL"])
def test_create_app_requires_both_module_urls(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("VISITS_DATABASE_URL", VISITS_URL)
    monkeypatch.setenv("BILLING_DATABASE_URL", BILLING_URL)
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        create_app()


def test_create_app_needs_no_other_connection_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISITS_DATABASE_URL", VISITS_URL)
    monkeypatch.setenv("BILLING_DATABASE_URL", BILLING_URL)
    for name in OTHER_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    app = create_app()
    assert set(app.openapi()["paths"]) == {
        "/api/visits",
        "/api/visits/{visit_id}",
        "/api/visits/{visit_id}/complete",
        "/api/visits/{visit_id}/start",
        "/api/visits/{visit_id}/cancel",
        "/api/visits/{visit_id}/missed",
        "/api/billing-records",
    }


def test_create_app_makes_command_log_lines_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract section 3, Logging: INFO lines reach stderr under uvicorn, whose default
    configuration leaves the root logger at WARNING without a handler."""
    monkeypatch.setenv("VISITS_DATABASE_URL", VISITS_URL)
    monkeypatch.setenv("BILLING_DATABASE_URL", BILLING_URL)
    create_app()
    create_app()  # idempotent: a second app adds no second handler
    app_logger = logging.getLogger("app")
    assert logging.getLogger("app.visits.api").isEnabledFor(logging.INFO)
    assert len([h for h in app_logger.handlers if isinstance(h, logging.StreamHandler)]) == 1
    assert app_logger.propagate is True  # pytest caplog and any root handler still see the lines

"""The API process reads only the Visits database URL (module-03 criterion on billing_app; D13)."""

import pytest

from app.main_api import create_app

OTHER_SETTINGS = ("BILLING_DATABASE_URL", "MIGRATIONS_DATABASE_URL", "RABBITMQ_URL")


def test_create_app_requires_visits_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISITS_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="VISITS_DATABASE_URL"):
        create_app()


def test_create_app_needs_no_other_connection_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISITS_DATABASE_URL", "postgresql+asyncpg://visits_app:x@localhost/jiris")
    for name in OTHER_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    app = create_app()
    assert {route.path for route in app.routes} >= {
        "/api/visits",
        "/api/visits/{visit_id}",
        "/api/visits/{visit_id}/complete",
        "/api/visits/{visit_id}/start",
        "/api/visits/{visit_id}/cancel",
        "/api/visits/{visit_id}/missed",
    }

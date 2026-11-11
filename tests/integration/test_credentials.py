"""TD-1 (module-08 task 3.1.5; DL-38): the session stack runs with random passwords, applied
through the same init.sql template that compose uses."""

import asyncpg
import pytest

from tests.integration.helpers import Stack

pytestmark = pytest.mark.integration

ROLES = ("visits_app", "billing_app", "jiris_migrator")


@pytest.mark.parametrize("role", ROLES)
async def test_roles_use_a_random_session_password(stack: Stack, role: str) -> None:
    password = stack.passwords[role]
    assert len(password) >= 20
    assert password != role
    url = next(u for u in stack.env.values() if f"//{role}:" in u)
    assert f"{role}:{password}@" in url


@pytest.mark.parametrize("role", ROLES)
async def test_the_former_literal_password_is_refused(stack: Stack, role: str) -> None:
    host_port = stack.visits_dsn.split("@", 1)[1]
    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(f"postgresql://{role}:{role}@{host_port}")


def test_broker_user_is_not_guest(stack: Stack) -> None:
    user_info = stack.rabbitmq_url.split("://", 1)[1].split("@", 1)[0]
    user, password = user_info.split(":", 1)
    assert user != "guest" and password != "guest"
    assert len(password) >= 20

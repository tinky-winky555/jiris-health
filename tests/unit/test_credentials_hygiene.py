"""TD-1 (module-08 task 3.1.4; contract §3, DL-38): no literal credential in compose, the
database bootstrap or the tests; every compose credential is a required ${VAR}; .env.example
lists every variable with an empty value."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
THIS_FILE = Path(__file__).resolve()

# user:password@ where both are the same word, the pattern of the former local credentials
SAME_USER_AND_PASSWORD = re.compile(r"\b(postgres|guest|visits_app|billing_app|jiris_migrator):\1@")
LITERAL_PASSWORD_ARGUMENT = re.compile(r"""password\s*=\s*["'][^"']+["']""", re.IGNORECASE)


def _sources() -> list[Path]:
    paths = [COMPOSE, *sorted((ROOT / "docker").rglob("*")), *sorted((ROOT / "tests").rglob("*.py"))]
    return [p for p in paths if p.is_file() and p.resolve() != THIS_FILE]


def test_no_same_user_and_password_anywhere() -> None:
    found = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in _sources()
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if SAME_USER_AND_PASSWORD.search(line)
    ]
    assert found == []


def test_no_literal_password_argument_in_tests() -> None:
    found = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in _sources()
        if p.suffix == ".py"
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if LITERAL_PASSWORD_ARGUMENT.search(line)
    ]
    assert found == []


def test_bootstrap_takes_passwords_from_variables() -> None:
    sql = (ROOT / "docker/postgres/init.sql").read_text()
    assert re.findall(r"PASSWORD\s+'", sql) == []
    for variable in ("migrator_password", "visits_password", "billing_password"):
        assert f"PASSWORD :'{variable}'" in sql
    assert (ROOT / "docker/postgres/init.sh").is_file()


def test_compose_credentials_are_required_variables_without_defaults() -> None:
    text = COMPOSE.read_text()
    for line in text.splitlines():
        if re.search(r"(PASSWORD|_USER)\s*:", line) and "POSTGRES_USER" not in line:
            assert "${" in line, line
        assert not re.search(r"\$\{[A-Z_]+:-", line), f"default value in: {line}"
    urls = re.findall(r"(?:postgresql\+asyncpg|amqp)://[^\s\"']+", text)
    assert urls, "no connection URL found"
    for url in urls:
        user_info = url.split("://", 1)[1].split("@", 1)[0]
        assert user_info.count("${") >= 1, url


def test_env_example_lists_every_compose_variable_with_an_empty_value() -> None:
    used = set(re.findall(r"\$\{([A-Z_]+)", COMPOSE.read_text()))
    example = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            example[key.strip()] = value.strip()
    assert used <= set(example), sorted(used - set(example))
    assert all(value == "" for value in example.values()), example

# Module 01, Repository foundation

Effort: 6 hours · Prerequisites: none · Built before the contract (as-built record)

## 1. Goal

Deliver a repository that installs on Python 3.15.2 with uv, holds the
TDD §4 layout, runs PostgreSQL and RabbitMQ locally, enforces module
boundaries with import-linter, and contains test T1 as the first failing
test. It does not deliver models, migrations or behaviour.

## 2. Prerequisites

- Empty repository `tinky-winky555/jiris-health` with `CLAUDE.md` and
  `docs/` (PRD, TDD, HANDOFF).
- Docker Desktop running; uv installed.

## 3. Tasks

3.1 Verify that compiled dependencies install from cp315 wheels
(asyncpg, pydantic-core, greenlet, uvloop, httptools, multidict, yarl)
on macOS and manylinux_2_28 (aarch64, x86_64); avoid pyyaml (DL-4).
3.2 `pyproject.toml`, `uv.lock`, `.python-version` (3.15.2).
3.3 Package layout per TDD §4 with docstring-only modules.
3.4 `.importlinter` with three contracts: visits and billing
independent; contracts imports neither; outbox imports neither.
3.5 `docker-compose.yml` (postgres, rabbitmq, migrate, api, worker),
`Dockerfile` on `python:3.15.2-slim`, `docker/postgres/init.sql` (roles
per TDD §9 and D29).
3.6 `tests/integration/test_t1_concurrent_complete.py`, run 50 times.
3.7 `.gitignore`: as built, a Node.js template with a Python block
appended (cleanup recorded as TD-2); `/tests` removed,
`.import_linter_cache/` added (DL-5).

## 4. Acceptance criteria

- [x] `uv sync` succeeds on a clean clone with Python 3.15.2.
- [x] `uv run lint-imports` reports 3 contracts kept.
- [x] `docker compose config` validates.
- [x] T1 exists, is collected 50 times, and is reported xfailed
  (`xfail(strict=True)`, contract DL-6) because the worker is not built;
  no collection or syntax error.
- [x] `git check-ignore tests/integration/test_t1_concurrent_complete.py`
  returns nothing.

Completion report: `gate-report-M01-IG-7.md`.

## 5. Out of scope

Models and migrations (M02); any endpoint (M03); relay and consumers
(M04 to M06).

## 6. What comes next

M02 creates the schemas, roles, models and both Alembic chains, and
makes the `migrate` service work from an empty database.

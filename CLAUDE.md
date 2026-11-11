# CLAUDE.md · Jiris Health

Modular monolith (FastAPI + PostgreSQL + RabbitMQ) with two modules, Visits and Billing. Every completed visit gets exactly one active billing record, even when the broker is down, events arrive twice, or two `/complete` requests race.

## Sources of truth (read before any change)

1. `docs/PRD.md`: what to build (FR, NFR, acceptance tests T1 to T8).
2. `docs/TDD.md`: how to build it (architecture, schema, algorithms, contract, configuration).
3. `docs/HANDOFF.md`: every decision (D1 to D30, R1 to R9) with its rationale.

Decisions are closed. Do not change one silently. If the code needs a deviation, stop, explain it in one paragraph, and ask. Anything not covered by the documents: propose, mark it `[PROPOSAL]`, and wait for approval.

## Invariants (never break)

- Visits and Billing never read or write each other's tables. They talk only through events in `app.contracts`. `app.visits` and `app.billing` never import each other (import-linter).
- State change and its event are written in one local transaction (outbox). Nothing publishes to RabbitMQ outside the relay.
- Consumers de-duplicate by `event_id` in their inbox and ack only after COMMIT.
- One active record per visit: partial unique index `(visit_id) WHERE status = 'Created'`.
- `/complete` uses the conditional UPDATE in TDD §6.2. The winner gets 202, everyone else 409.
- Visits applies a Billing reply only when `completion_attempt_id` matches.
- Money is `Decimal`, 2 places, ROUND_HALF_UP; it travels in events as a decimal string.

## Way of working

- Test first. Write the acceptance test from PRD §8 before the code that makes it pass. Start with T1.
- Small increments, in this order: scaffolding and compose → schemas, roles, migrations → `/complete` and outbox → relay → Billing consumer → Visits consumer → failure paths → purge job.
- After each increment run the full test suite and import-linter. Do not move on while anything is red.
- Integration tests use real PostgreSQL and RabbitMQ (testcontainers), never mocks of them.
- Keep the docs in step: if behaviour changes with approval, update `docs/TDD.md` in the same change.

## Stack

Python 3.15.2 or later · FastAPI · SQLAlchemy 2 async + asyncpg · Alembic (two chains: `visits`, `billing`) · FastStream over aio-pika · Pydantic · pytest, httpx, testcontainers · import-linter · docker-compose (postgres, rabbitmq, api, worker).

First task: check that the compiled dependencies (asyncpg, pydantic-core) install on Python 3.15. If not, report before choosing a workaround.

## Configuration

`VISITS_DATABASE_URL`, `BILLING_DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `RABBITMQ_URL`. Relay: poll 500 ms, batch 100, backoff ceiling 30 s. Outbox retention 7 days. Billing transient retries: 5.

## Commands

Package manager: uv (`pyproject.toml`, `uv.lock`, Python pinned in `.python-version`).

- Install: `uv sync`
- Run locally: `docker compose up`
- Tests: `uv run pytest`
- Boundaries: `uv run lint-imports`
- Migrations: `uv run alembic -n visits upgrade head`, `uv run alembic -n billing upgrade head`

## Definition of done

T1 to T8 green (T1 run 50 times), import-linter green, migrations apply from empty, `docker compose up` starts all four services, README explains how to run and test.

## Writing

Code, comments, commits and docs in British English. No em dash or en dash.

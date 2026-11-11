# Jiris Health

Visits and Billing modular monolith (FastAPI, PostgreSQL, RabbitMQ). See `docs/PRD.md`, `docs/TDD.md` and `docs/HANDOFF.md`.

Work in progress: scaffolding only. Run and test instructions will be completed as the increments land.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.15.2 from `.python-version`)
- Docker (integration tests use testcontainers)

## Commands

```sh
uv sync                 # create .venv with all dependencies
uv run pytest           # full test suite
uv run lint-imports     # module boundaries
docker compose up       # postgres, rabbitmq, api, worker
```

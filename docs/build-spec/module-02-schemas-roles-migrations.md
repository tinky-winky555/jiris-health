# Module 02, Schemas, roles, migrations

Effort: 8 hours · Prerequisites: M01 · Built before the contract (as-built record)

## 1. Goal

Deliver the data layer of TDD §5 for both modules, the database roles
and grants of TDD §9 and §9.1 (DL-1), and two Alembic chains run by
`jiris_migrator` through the `migrate` service. It does not deliver any
query used by behaviour, nor endpoints.

## 2. Prerequisites

- M01 acceptance criteria pass.

## 3. Tasks

3.1 Write T7 first: each application role cannot read the other schema,
can read and write its own tables (INSERT, UPDATE and DELETE checked in a
rolled-back transaction, added at adoption, contract DL-9), cannot run
DDL and cannot touch `alembic_version`; import-linter passes.
3.2 SQLAlchemy models for `visits` (visit, outbox, inbox) and `billing`
(billing_record, outbox, inbox) with the CHECK constraints of TDD §5,
`ux_active_record`, and the outbox partial index
`WHERE published_at IS NULL`.
3.3 `alembic.ini` with `[visits]` and `[billing]`; one `env.py` per
chain; first revision per chain; version table in its own schema;
migrations under `MIGRATIONS_DATABASE_URL`.
3.4 Grants per named table plus `ALTER DEFAULT PRIVILEGES` (DL-1,
TDD §9.1).
3.5 `test_migrations.py`: `alembic -n <chain> check` fails when models
and migrations diverge.
3.6 `migrate` compose service runs both chains; `api` and `worker`
depend on it with `condition: service_completed_successfully` (BS-4).

## 4. Acceptance criteria

- [x] T7 passes, including the `alembic_version` restriction for both
  application roles.
- [x] `test_migrations.py` passes, and fails when a column is added to a
  model without a migration (demonstrated once, reverted).
- [x] `docker compose up migrate` on an empty volume exits 0.
- [x] `alembic -n visits downgrade base` then `upgrade head` succeeds;
  the same for `billing`.
- [x] `uv run lint-imports` reports 3 contracts kept.
- [x] T1 remains collected 50 times; its state follows contract DL-6
  (`xfail(strict=True)`).

Completion report: `gate-report-M02-IG-7.md`.

## 5. Out of scope

Any repository or service code (M03 onwards); seed data; the purge job
(M08).

## 6. What comes next

M03 builds the Visits HTTP API and the completion transaction that
writes VisitCompleted to the outbox.

# Gate report M02, IG-7 (completion), Schemas, roles, migrations

Module: `module-02-schemas-roles-migrations.md` · Date: 2026-11-11 ·
Retrospective: M02 was built before the contract and committed as
`aed4672` on `build/increments`. No planning report exists (contract
section 4). Evidence was collected from the repository as it stands at
adoption, including the T7 write case added at adoption (DL-9).

## IG-4. Implementation consistent with the approved scope

- Models (`app/visits/models.py`, `app/billing/models.py`) and the first
  revisions (`visits_0001`, `billing_0001`) hold the tables and columns
  of TDD §5.1 and §5.2, the CHECK constraints for the time range, the
  positive rate and every status set, `ux_active_record` on
  `billing.billing_record (visit_id) WHERE status = 'Created'`, and
  `ix_outbox_unpublished` on `outbox (occurred_at) WHERE published_at IS
  NULL` in both schemas.
- `alembic.ini` has the sections `[visits]` and `[billing]`; each
  `env.py` reads `MIGRATIONS_DATABASE_URL`, runs `CREATE SCHEMA IF NOT
  EXISTS` first and keeps the version table in its own schema.
- Grants per named table plus `ALTER DEFAULT PRIVILEGES IN SCHEMA`, as
  DL-1 (approved) and TDD §9 and §9.1.
- `migrate` is a one-shot compose service; `api` and `worker` depend on
  it with `condition: service_completed_successfully` (BS-4).
- Out of scope respected: at `aed4672`, `service.py`, `api.py`,
  `consumer.py` and `relay.py` hold a docstring only; no seed data; no
  purge job.
- Change at adoption: T7 gained `test_t7_role_writes_own_schema` (INSERT,
  UPDATE and DELETE on each own table, in a rolled-back transaction),
  because task 3.1 promised a write check that T7 did not hold
  (reconciliation item 15).
- Not as BS-3: committed directly on `build/increments` before BS-3
  existed (DL-7).

## IG-5. Validation

| Criterion | State | Evidence |
|---|---|---|
| T7 passes, including the `alembic_version` restriction for both application roles | Met | `uv run pytest tests/integration/test_t7_module_isolation.py`: 21 passed (6 foreign table reads refused, 2 own reads, 2 own writes, 2 DDL refused, 8 `alembic_version` statements refused, 1 import-linter) |
| `test_migrations.py` passes, and fails when a column is added to a model without a migration (demonstrated once, reverted) | Met | Passes in the suite (2 passed). Demonstration on a scratch copy: column `drift_probe` added to `Visit`; `alembic -n visits check` exit 255, `New upgrade operations detected: [('add_column', 'visits', 'visit', Column('drift_probe', Text(), ...))]`; the billing case passed; the copy was deleted, the repository was never changed |
| `docker compose up migrate` on an empty volume exits 0 | Met | Isolated compose project `jiris-ig7-check` with a new volume: `Running upgrade -> visits_0001`, `Running upgrade -> billing_0001`, `migrate-1 exited with code 0`; project removed with `down -v` |
| `alembic -n visits downgrade base` then `upgrade head` succeeds; the same for `billing` | Met | Same isolated project, `docker compose run --rm migrate`: downgrade and upgrade of both chains, exit 0; `alembic current` gives `visits_0001 (head)` and `billing_0001 (head)` |
| `uv run lint-imports` reports 3 contracts kept | Met | `Contracts: 3 kept, 0 broken.` |
| T1 remains collected 50 times; its state follows contract DL-6 | Met | 50 collected, 50 xfailed with reason `needs relay and consumers; removed in M06` |

Verdict tally: 6 met, 0 not met, 0 not verified.

Full suite at adoption: 73 collected, 23 passed, 50 xfailed. This total
is the baseline for M03 (definition of done, item 6).

Database actions ran only on testcontainers and on the throwaway compose
project `jiris-ig7-check`; the developer's compose volume was not
touched (HG-3 not engaged).

## IG-6. Documentation

- `docs/TDD.md` §9: the `ON ALL TABLES` block replaced by the as-built
  bootstrap and grants, under DL-1.
- `docs/build-spec/index.md` section e: index naming convention aligned
  with the as-built names (`ix_<table>_<purpose>`, `ux_<purpose>`,
  `ck_<table>_<purpose>`).
- `module-02-schemas-roles-migrations.md`: task 3.1 states the write
  check; criteria ticked from this report.
- `CLAUDE.md` COMMANDS: drift check prerequisites stated.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| The `alembic_version` restriction relies on the version table being created before `ALTER DEFAULT PRIVILEGES` runs; a version table recreated later in the same schema would receive DML for the application role | Application role could edit migration history | T7 checks it permanently (DL-1); never drop `alembic_version` by hand |
| Default privileges apply only to tables created by `jiris_migrator` | A table created by another role would get no DML grant | Migrations run only as `jiris_migrator` (CLAUDE.md) |
| `migrate` receives the whole application environment, including both application role URLs, though it needs only `MIGRATIONS_DATABASE_URL` | Broader configuration than needed in one container | Review with TD-1 in M08 |
| The drift check needs a database at head; it is not a standalone command | `uv run alembic -n <chain> check` fails without the environment | Documented in CLAUDE.md; the suite runs it |
| Local credentials in init.sql | As TD-1 | TD-1, close in M08 |

Registers: no new entry from M02 beyond TD-1 (shared with M01).

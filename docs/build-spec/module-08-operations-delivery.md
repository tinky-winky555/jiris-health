# Module 08, Technical debt and operations

Effort: 11 hours (split approved, DL-37: the README, the definition of
complete and the release move to M09, 4 hours) · Prerequisites: M01 to
M07

## 1. Goal

Deliver the outbox purge job (R5, D25), prove the broker reconnection of
relays and consumers (R7, NFR5) beyond the restart of T3, and close the
open technical debt TD-1, TD-2, TD-3, TD-4, TD-6 and TD-7, with the
operational follow-ups of earlier modules (OQ-28). After M08 no technical
debt targeted at this release is open. It does not write the README,
audit the definition of complete or merge into `main` (M09).

## 2. Prerequisites

- M07 acceptance criteria pass; M07 merged into `build/increments`
  (`64ef30c`).
- HG-1 on this document and `gate-report-M08-IG-3.md` given by Sasha on
  2026-11-11, with OQ-24 to OQ-28 answered (DL-37 to DL-41).

## 3. Tasks

3.1 Tests first (each seen failing before its code):
- 3.1.1 Integration, purge (R5, D25): for each schema, as its own role,
  one pass deletes outbox rows published more than 7 days ago; keeps rows
  published within 7 days; keeps every unpublished row whatever its age,
  including a row excluded by the relay (`attempts = 5`); deletes more
  rows than one batch over several batches; a second pass deletes
  nothing.
- 3.1.2 Integration, worker: the worker runs the purge for both schemas
  at start and then every hour (configurable for the test), one log line
  per pass with the schema and the number of rows deleted.
- 3.1.3 Integration, R7 (dedicated broker): a worker started while the
  broker is down connects with backoff once it is up and becomes ready;
  `rabbitmqctl close_all_connections` on a running worker is followed by
  automatic recovery of both relays and both consumers, and a `/complete`
  issued afterwards ends Completed; the worker log shows the reconnection,
  and the process never restarts.
- 3.1.4 Unit, TD-1 (OQ-25): `docker-compose.yml`, `docker/postgres/` and
  `tests/` hold no literal password; every credential in compose is a
  `${VAR}` reference with no default; `.env.example` lists every variable
  compose uses, with empty values; `migrate` receives only
  `MIGRATIONS_DATABASE_URL`.
- 3.1.5 Integration, TD-1: the session stack starts with random passwords
  for the three database roles and the broker user, generated per
  session, applied through the same `init.sql` template that compose
  uses.
- 3.1.6 Unit, TD-4: a 422 on `POST /api/visits` and on
  `GET /api/billing-records` writes one command log line (`outcome=422`,
  the path) and returns FastAPI's validation body unchanged.
- 3.1.7 Unit, TD-6 (OQ-26): `is_database_unavailable()` is true for
  connection errors, SQLSTATE class 08, 57P01 to 57P03, 40001 and 40P01;
  false for an `OperationalError` with any other SQLSTATE; Billing's
  `classify()` and the Visits consumer follow.
- 3.1.8 Unit and integration, TD-7: Billing writes a stable code in
  `BillingFailed.reason`: `invalid_payload` (non-positive duration or
  rate), `amount_out_of_range` (SQLSTATE 22003), `invalid_data` (other
  class 22), `constraint_violation` (class 23 except 23505),
  `transient_errors_exhausted`; the raw exception text goes to
  `billing.inbox.last_error` only. T4 and T5 assert the codes; the body of
  `GET /api/visits/{id}` after a failure contains none of `Error`,
  `sqlalchemy`, `asyncpg`, `Traceback`, nor the raw message.
- 3.1.9 Unit, TD-2 (OQ-27): `.gitignore` keeps `.env*` with
  `!.env.example`, `.import_linter_cache/`, the Python caches and `.venv/`;
  it holds no Node.js, Next.js or Vercel entry and no unrelated path;
  `git check-ignore` returns nothing for every tracked file; `.env` is
  ignored and `git add .env` is refused (DL-38).
- 3.1.10 Unit, OQ-28: compose gives `api` and `worker` a restart policy;
  FastStream's own loggers run at WARNING through our format.
3.2 `app/outbox/purge.py` (new): `OutboxPurge(schema, engine, retention =
7 days, batch_size = 1000)`; `run_once()` deletes in batches of
`DELETE ... WHERE event_id IN (SELECT event_id ... WHERE published_at <
now() - retention LIMIT batch_size)`; the worker loop runs it hourly; the
schema name checked as in the relay.
3.3 `app/main_worker.py`: the purge loop for both schemas; FastStream log
level (OQ-28).
3.4 TD-1: `docker-compose.yml` with `${...}` only; `docker/postgres/init.sql`
as a psql variable template; `docker/postgres/init.sh` (new);
`.env.example` keys; `tests/integration/conftest.py` with random session
passwords; `migrate` environment reduced (OQ-28).
3.5 TD-3: `docker buildx build --platform linux/amd64 .` and, in that
image, an import of asyncpg, pydantic-core, greenlet, uvloop, httptools,
multidict and yarl; result recorded in the IG-7 report (not part of the
suite: QEMU emulation takes minutes).
3.6 TD-4: a `RequestValidationError` handler in `app/main_api.py` that
logs the line and delegates to FastAPI's default handler.
3.7 TD-6: `is_database_unavailable()` narrowed in `app/outbox/consumer.py`.
3.8 TD-7: `failure_reason()` in `app/billing/service.py`; the code list in
TDD §7 (BillingFailed `reason`); the contract model keeps `reason: str`,
no schema version change.
3.9 TD-2: `.gitignore` rewritten.
3.10 Registers: TD-1, TD-2, TD-3, TD-4, TD-6, TD-7 to Done with the
closing evidence; contract §7b; TDD §8.1 (purge), §7, §8.2 updated (IG-6).

## 4. Acceptance criteria

- [x] Every test of task 3.1 passes.
- [x] R5: published rows older than 7 days are purged in both schemas;
  unpublished rows never are.
- [x] R7: the worker recovers from a broker that is down at start and from
  closed connections, with no restart and no manual step.
- [x] No literal credential remains in compose, `docker/postgres/` or the
  tests; `docker compose up` from an empty volume with a filled `.env`
  starts postgres, rabbitmq, migrate (exit 0), api and worker.
- [x] The amd64 image builds and imports every compiled dependency.
- [x] No exception text reaches an API response.
- [x] TD-1, TD-2, TD-3, TD-4, TD-6, TD-7 are Done; contract §7b matches
  `docs/technical-debt.md`.
- [x] The suite passes in file order and with the T1 module first;
  `lint-imports` 3 kept; both `alembic check`; T1 to T8 green.
- [x] Collected test count is at least 353 plus the new tests.

Completion report: `gate-report-M08-IG-7.md`.

## 5. Out of scope

| Item | Destination |
|---|---|
| README, index section g audit, merge into `main` under HG-3 | M09 (DL-37) |
| Inbox retention | Backlog FB-5, next release |
| Replay tooling for parked messages | Not in this release |
| LISTEN/NOTIFY, reversal, `Idempotency-Key` | Backlog FB-3, FB-1, FB-2 |

## 6. What comes next

M09 writes the README, audits the definition of complete (index section
g) from a clean clone and, under HG-3, merges `build/increments` into
`main`.

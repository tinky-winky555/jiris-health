# Gate report M08, IG-7 (completion), Technical debt and operations

Module: `module-08-operations-delivery.md` · Date: 2026-11-11 · Branch:
`feature/m08-operations-delivery` (from `build/increments` at `64ef30c`)
· Planning report: `gate-report-M08-IG-3.md`, approved with HG-1 on
2026-11-11 (DL-37 to DL-41).

## Commits on the branch

| Commit | Content |
|---|---|
| `9a4a12a` | docs: HG-1 record; split into M08 and M09 (DL-37); index sections b, c, d, g; contract DL-37 to DL-41; FB-5 |
| `63d791e` | test: M08 tests, committed red |
| `767e102` | feat: `app/outbox/purge.py`; purge loop and FastStream logger in `app/main_worker.py` |
| `52df037` | build: TD-1: compose from `.env`, `init.sql` template, `init.sh`, `.env.example`, random test passwords, reduced `migrate` and `api` environments, restart policy |
| `6fc187c` | feat: TD-4: 422 command log line |
| `1868a56` | fix: TD-6: classifier narrowed by SQLSTATE |
| `bb3c208` | feat: TD-7: stable reason codes |
| `33f1bd7` | chore: TD-2: `.gitignore` rewritten |
| `9524819` | docs: registers closed; TDD §7, §8.1, §8.2, §9.1, §10 |

## Red run (tests first)

| After | Result |
|---|---|
| `63d791e`, tests | 355 passed, 35 failed, 2 errors: `test_billing_reason.py` (`REASON_CODES` missing) and `test_outbox_purge.py` (`app.outbox.purge` missing) not collectable; failed: credential hygiene (literal passwords in compose, `init.sql`, conftest, helpers, two consumer tests), credentials and compose configuration tests, `.gitignore` foreign entries, 422 logging, the TD-6 cases and the two moved M07 cases, the TD-7 service, T4 and T5 assertions, the worker purge test. Both R7 tests passed already: the worker's connection backoff (M04) and the robust connection recover from a broker down at start and from closed connections without new code; they are the R7 confirmation |
| `767e102`, purge | First run: `operator does not exist: timestamp with time zone < interval` (an untyped bound parameter in `now() - $1`); fixed with `CAST(:retention AS interval)`; then purge and worker tests 8 passed |
| `52df037`, TD-1 | Credential, compose, T7 and migration tests 42 passed; full suite: only the TD-2, TD-4, TD-6, TD-7 tests still red |
| `6fc187c`, `1868a56`, `bb3c208`, `33f1bd7` | 91, 42, 30 and 4 passed respectively |

## IG-4. Implementation consistent with the approved scope

- R5: `OutboxPurge` deletes, per schema as its own role, published rows
  with `published_at < now() - 7 days`, by batches of 1000 with `FOR
  UPDATE SKIP LOCKED`; never an unpublished row; the worker starts both
  purges before reaching the broker, then hourly; one INFO line per pass.
- R7: no code; the two new tests confirm recovery from a broker that is
  down at start (backoff, then ready, then a completion) and from
  `rabbitmqctl close_all_connections` (consumers back, completion, no
  process restart); T3 still covers the restart.
- TD-1: `docker-compose.yml` uses `${VAR:?message}` for every credential,
  no default; `docker/postgres/init.sql` is a template with `:'migrator_password'`,
  `:'visits_password'`, `:'billing_password'`, run by `init.sh` (`psql -v`);
  `.env.example` lists the six compose variables and the four application
  URLs, all empty; the test session generates the superuser, role and
  broker passwords and renders the same template; `.env` is ignored and
  refused by `git add`.
- OQ-28: `migrate` receives only `MIGRATIONS_DATABASE_URL`; `api` only the
  two module URLs (it no longer waits for RabbitMQ, which it never uses);
  `api` and `worker` restart `unless-stopped`; FastStream logs through
  `app.faststream` at WARNING in the worker's format.
- TD-2: `.gitignore` holds only `.env*`/`!.env.example`, Python and uv,
  test and lint caches, editor and OS files, the developer's Claude Code
  settings, logs.
- TD-3: amd64 build and import check (IG-5).
- TD-4: `RequestValidationError` handler logs `command=<name> visit_id=...
  outcome=422 path=<path>` on logger `app.api`, then FastAPI's default
  body.
- TD-6: `is_database_unavailable()`: connection-level classes (OS errors,
  timeouts, asyncpg connection errors, 53300), SQLSTATE class 08, 57P01
  to 57P03, 40001, 40P01, or a SQLAlchemy operational or interface error
  without a SQLSTATE; any other SQLSTATE is counted.
- TD-7: `failure_reason()` maps to the five codes; `_billing_failed()`
  refuses any other value; `describe()` text goes to `last_error` only.
- Out of scope respected: no README, no audit of index section g, no
  merge into `main` (M09); no inbox retention (FB-5); no schema change.

## IG-5. Validation

From a clean clone of the branch at `9524819` (`git clone`, `uv sync`):
404 collected, 404 passed; `lint-imports` 3 kept.

| Criterion | State | Evidence |
|---|---|---|
| Every test of task 3.1 passes | Met | `test_outbox_purge.py` 6, `test_worker.py` 2, `test_r7_reconnection.py` 2, `test_credentials_hygiene.py` 5, `test_credentials.py` 7, `test_compose_config.py` 7, `test_validation_logging.py` 2, `test_consumer_mechanics.py` 25, `test_billing_reason.py` 8, `test_gitignore.py` 4, T4, T5: all passed |
| R5: published rows older than 7 days purged in both schemas; unpublished never | Met | Per schema: 8 days and 7 days plus 1 minute deleted; 7 days minus 1 minute kept; unpublished 30 days old kept; excluded (`attempts = 5`) kept; second pass 0; 25 rows over batches of 10 deleted; the worker logged `outbox purged schema=visits` and `schema=billing` at start and removed rows 9 days old |
| R7: recovery from a broker down at start and from closed connections, no restart, no manual step | Met | Worker alive with `broker connection failed` while down, ready after the broker returned, a completion ended Completed; after `close_all_connections` both inbox queues had their consumer back and a completion ended Completed, process never restarted. Three further runs: 3 of 3 |
| No literal credential; `docker compose up` from an empty volume with a filled `.env` starts every service | Met | Hygiene tests; `docker compose config` without values fails with "required variable ... is missing a value"; isolated project `jiris-m08-check` with a generated env file outside the repository: postgres, rabbitmq, api, worker running, migrate exit 0, the three roles created by `init.sh`, `/complete` ended Completed; project removed with `down -v`, env file deleted |
| The amd64 image builds and imports every compiled dependency | Met | `docker buildx build --platform linux/amd64 .` exit 0 in 11 s, 30 packages from wheels, none built from source; in the image `x86_64`, asyncpg 0.32.0, pydantic-core 2.50.4, greenlet 3.5.6, uvloop 0.23.0, httptools 0.9.0, multidict 7.2.1, yarl 1.25.1, SQLAlchemy, FastStream imported, exit 0; image removed |
| No exception text reaches an API response | Met | T4 and T5: the body of `GET /api/visits/{id}` holds none of `Error`, `sqlalchemy`, `asyncpg`, `Traceback`, `overflow`, `injected`; `completion_failure_reason` is `amount_out_of_range` and `transient_errors_exhausted`; `last_error` keeps `numeric field overflow` |
| TD-1, TD-2, TD-3, TD-4, TD-6, TD-7 Done; contract §7b matches the register | Met | `docs/technical-debt.md`: all seven entries Done with closing evidence; contract §7b: same seven, "No technical debt is open" |
| Suite in file order and with the T1 module first; lint; both `alembic check`; T1 to T8 | Met | File order 404 passed (196.2 s); T1 module first 404 passed (186.9 s); `Contracts: 3 kept, 0 broken.`; `test_models_match_migrations` 2 passed; T1 50, T2, T3, T4, T5, T6, T7 21, T8 green |
| Collected count at least 353 plus the new tests | Met | 404 collected (353 plus 51) |

Verdict tally: 9 met, 0 not met, 0 not verified.

Also seen in the compose run: a 422 on `POST /api/visits` logged as
`INFO app.api command=create visit_id=- event_id=- event_type=-
outcome=422 path=/api/visits`; the worker log had no ANSI escape sequence
and showed `outbox purged`, `topology declared` and one `event consumed`
line per module.

Branch and count after each commit: `git branch --show-current` returned
`feature/m08-operations-delivery` after every commit. Collected totals:
353 after `9a4a12a`; not collectable in full after `63d791e` and
`767e102` (the reason module imports `REASON_CODES`, added in
`bb3c208`); 404 from `33f1bd7` onwards (checked after `33f1bd7` and
`9524819`).

## IG-6. Documentation

- `docs/TDD.md`: §7 BillingFailed reason codes; §8.1 purge; §6.4 and §8.2
  the narrowed definition of "database unavailable" and the accepted
  risk; §9.1 bootstrap template; §10 purge interval and batch.
- `docs/technical-debt.md`: TD-1, TD-2, TD-3, TD-4, TD-6, TD-7 Done.
- `docs/feature-backlog.md`: FB-5 (inbox retention, next release).
- `docs/build-spec/contract.md`: §5, §6 DL-37 to DL-41, §7a resolved
  OQ-24 to OQ-28, §7b.
- `docs/build-spec/index.md`: sections b (M08 11 h, M09 4 h, total 73),
  c, d (`app/outbox/purge.py`, `docker/postgres/init.sh`), g.
- `module-08-operations-delivery.md`: criteria ticked from this report.
- The README is M09's (DL-37); until then the run procedure with `.env`
  is in `.env.example` and in this report.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| TD-6 keeps SQLSTATE 53300 (too many connections) as unavailable, through `asyncpg.TooManyConnectionsError`, although the TD-6 list names 08, 57P, 40001 and 40P01 only | Under connection exhaustion a reply is retried without counting instead of being counted towards parking | For the developer's approval at this gate: counting 53300 could fail billing under load for want of a connection, which no retry limit should decide |
| Accepted risk (DL-39): a deterministic deadlock or serialisation failure from a bug repeats for ever | Visible only as WARNING lines with `cause=database_unavailable` | Accepted by the developer |
| `docker compose up` now needs a filled `.env` | A new developer who skips it gets a compose error naming the variable | README in M09 |
| Inbox tables grow without bound | Storage growth over time | FB-5, next release |
| The purge runs in every worker; with several workers, passes overlap | Harmless: `SKIP LOCKED` and idempotent deletes | Accepted |

Registers: TD-1, TD-2, TD-3, TD-4, TD-6, TD-7 closed; no new technical
debt; FB-5 added at HG-1.

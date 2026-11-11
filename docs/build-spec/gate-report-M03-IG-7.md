# Gate report M03, IG-7 (completion), Visits API, completion endpoint and outbox write

Module: `module-03-visits-api-and-outbox.md` · Date: 2026-11-11 · Branch:
`feature/m03-visits-api-and-outbox` (from `build/increments` at
`8c1a741`) · Planning report: `gate-report-M03-IG-3.md`, approved with
HG-1 on 2026-11-11 (DL-13 to DL-17).

## Commits on the branch

| Commit | Content |
|---|---|
| `61bfffe` | docs: HG-1 record, module-03 amendments, IG-3 report, DL-13 to DL-17, TD-3 |
| `1069c17` | test: T1 marker narrowed to `raises=WorkerNotReady` (DL-17) |
| `d1d9191` | test: M03 tests, committed red |
| `0c8bcb8` | feat: envelope and VisitCompleted in `app.contracts` |
| `f5338fb` | test: route check through the OpenAPI paths (test defect fixed) |
| `f99bdc8` | feat: Visits HTTP API and the completion outbox write |
| `1a8cdd7` | docs: TDD §6, §6.1, §6.3 and contract §3 (DL-10 to DL-13) |
| `39dded7` | test: visible command log lines under uvicorn, committed red |
| `9764cfb` | feat: `app` logger handler in the API process |

## Red runs (tests first, DL-8)

| After | Result |
|---|---|
| `1069c17`, T1 narrowing | 73 collected, 23 passed, 50 xfailed with `WorkerNotReady`. Shown on a scratch copy: the same fixture raising `RuntimeError` makes T1 an error, not an xfail |
| `d1d9191`, M03 tests | 23 passed, 50 xfailed, 4 collection errors: `ImportError` on `create_app` (app.main_api), `VISIT_COMPLETED` and `VisitCompleted` (app.contracts), `VisitCreate` (app.visits.api) |
| `0c8bcb8`, contracts | 32 passed (9 contract tests green), 50 xfailed, 87 errors: 85 integration tests at setup (`create_app` missing), 2 unit modules at collection |
| `f99bdc8`, API code | 129 passed, 1 failed: `test_create_app_needs_no_other_connection_setting` raised `AttributeError` on `_IncludedRouter.path`, a defect of the test, fixed in `f5338fb` by reading `app.openapi()["paths"]`; then 130 passed, 50 xfailed |
| `39dded7`, logging test | 1 failed: the `app` logger was not enabled for INFO and had no handler; green after `9764cfb` |

## IG-4. Implementation consistent with the approved scope

- `app.contracts`: `Envelope`, `VisitCompleted`, `EventSpec`,
  `VISIT_COMPLETED`, `new_envelope`, `Money` (2 places, ROUND_HALF_UP,
  decimal string, floats refused), `Timestamp` (UTC, `Z`). No Billing
  reply models and no exchange constants (DL-14).
- `app.visits.service`: conditional UPDATE for `/complete` with the
  predicate and SET of TDD §6.2, returning the whole row (the emitted SQL
  was read once: one `UPDATE visits.visit SET completion_requested_at=now(),
  completion_attempt_id=..., completion_failure_reason=... WHERE id = ...
  AND status IN (...) AND completion_requested_at IS NULL RETURNING ...`),
  then the outbox INSERT with `event_id = completion_attempt_id`, in the
  caller's transaction. Transitions use the same pattern, so `/start`,
  `/cancel` and `/missed` are refused while pending (R2, DL-11).
- `app.visits.api`: routes of TDD §6.1 for visits; 201, 200, 202; 404
  with `{"detail": "Not Found"}` (DL-10); 409 with the reason; 422 as
  FR11, DL-12, DL-13. The body is built inside the transaction and sent
  after COMMIT. One log line per command after COMMIT or rollback.
- `app.main_api`: one pool as `visits_app` from `VISITS_DATABASE_URL`;
  no other URL read; the `app` logger gets one named stderr handler at
  INFO (uvicorn configures only its own loggers).
- Test harness: `api_app` no longer depends on the worker; T1 requests
  `worker` explicitly.
- Out of scope respected: nothing publishes to RabbitMQ; no
  `GET /api/billing-records`; no reply handling; `app/billing`,
  `app/outbox`, `app/main_worker.py`, migrations, compose, Dockerfile and
  `.importlinter` unchanged (`git diff --stat build/increments..HEAD`
  touches only `app/contracts`, `app/visits/api.py`,
  `app/visits/service.py`, `app/main_api.py`, `tests/` and `docs/`).
- Difference from the pre-contract draft: Billing reply models removed
  (DL-14); 50 race runs instead of 20; tests added for the row lock, the
  reset, the configuration and the log lines; logging and return
  annotations added.

## IG-5. Validation

All runs below are from a clean clone of the branch (`git clone`,
`uv sync`), unless stated.

| Criterion | State | Evidence |
|---|---|---|
| Every test of task 3.1 passes | Met | `tests/unit/test_t8_visit_validation.py` 11 passed (3.1.1); `tests/integration/test_visits_api.py` 85 passed (3.1.2 to 3.1.9); `tests/unit/test_contracts.py` 9 passed (3.2); `tests/unit/test_main_api.py` 3 passed (3.1.9) |
| 3.1.6 passes 50 of 50 runs | Met | `test_concurrent_complete_has_one_winner_and_one_event[0..49]`: 50 passed. 3.1.7 (`test_complete_waits_for_the_row_lock_then_loses`) passed: the request waited on a row lock seen in `pg_stat_activity` and answered 409 `completion_pending` only after the holder committed |
| After a `/complete`, the unpublished outbox count for the visit under test equals 1 and the payload validates against VisitCompleted (DL-15) | Met | `test_complete_accepts_and_writes_one_outbox_event[Scheduled]` and `[In Progress]`: `_unpublished_count == 1`, `VisitCompleted.model_validate(payload)`. Also in compose: `visits.outbox` holds one `VisitCompleted` row with `published_at` NULL |
| The API process opens no connection as `billing_app` | Met | `create_app()` reads only `VISITS_DATABASE_URL` and starts with the other three settings removed (`test_create_app_needs_no_other_connection_setting`); T7 21 passed |
| `uv run lint-imports` passes; `alembic -n visits check` and `alembic -n billing check` pass | Met | `Contracts: 3 kept, 0 broken.`; `test_models_match_migrations[visits]` and `[billing]` passed |
| Collected test count is at least the M02 total plus the new tests | Met | 181 collected (M02 baseline 73, plus 108 new): 131 passed, 50 xfailed (T1, `WorkerNotReady`) |

Verdict tally: 6 met, 0 not met, 0 not verified.

Smoke run on an isolated compose project (`jiris-m03-check`, removed with
`down -v`): `POST /api/visits` 201; `/complete` 202 with
`completion_pending: true`; second `/complete` 409
`{"reason":"completion_pending"}`; `docker compose logs api` shows three
lines, for example `INFO app.visits.api command=complete visit_id=...
event_id=... event_type=VisitCompleted outcome=202`.

Branch and count after each commit: `git branch --show-current` returned
`feature/m03-visits-api-and-outbox` after every commit except `39dded7`,
where it was not run; the next commit, `9764cfb`, was checked on the same
branch. Collected totals: 73 after `61bfffe` and `1069c17`; not
collectable in full after `d1d9191` (4 modules) and `0c8bcb8` (2 modules)
by design of the red runs; 180 after `f5338fb`, `f99bdc8` and `1a8cdd7`;
181 after `39dded7` and `9764cfb`. The total never fell below the
baseline of 73 once the suite was collectable.

## IG-6. Documentation

- `docs/TDD.md`: §6 state machine note (start refused while pending,
  DL-11); §6.1 creation rules (DL-12, DL-13) and `/start` row; §6.3 404
  body (DL-10).
- `docs/build-spec/contract.md`: §3 Error shape (DL-10); §5; §6 DL-13 to
  DL-17; §7a resolved OQ-5 to OQ-8; §7b TD-3 and TD-4.
- `module-03-visits-api-and-outbox.md`: amended at HG-1 (tasks 3.1.7 to
  3.1.9, 3.3 wording, 3.7); criteria ticked from this report.
- `docs/technical-debt.md`: TD-4.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| 422 responses on creation are not logged by the command logger: FastAPI rejects the body before the handler runs | Contract section 3 asks one line per command; rejected creations leave no line | TD-4, close in M08 with a `RequestValidationError` handler that logs and keeps the FastAPI body |
| The row-lock test finds the waiting request through `pg_stat_activity` with `query LIKE 'UPDATE visits.visit%'` | A change in the SQL SQLAlchemy emits (for example a leading comment) would make the test time out, not pass silently | Accepted; the test fails loudly after 10 s |
| A `rate` sent as a JSON number (for example `25.1`) is accepted and converted to the same Decimal as the string; only strings are documented | None observed; a client may rely on numbers | Accepted; strings remain the documented form (index section e) |
| `uuid7` ids reveal the creation time of a visit | Minor information exposure through ids | Accepted; no authentication in this release |
| GET requests also write a log line (`command=read`) | Log volume grows with polling clients | Accepted; reviewed with logging in M08 |
| T1 still xfails at setup until M06 | As M01 report; now narrowed to `WorkerNotReady` (DL-17) | M06 removes the marker |

Registers: TD-4 opened and mirrored in contract section 7b. No backlog
entry.

# Gate report M03, IG-3 (planning), Visits API, completion endpoint and outbox write

Module: `module-03-visits-api-and-outbox.md` · Date: 2026-11-11 ·
Branch: `feature/m03-visits-api-and-outbox`, created from
`build/increments` at `8c1a741` · Baseline: 73 collected, 23 passed, 50
xfailed.

Starting point: a draft of this module was written before the contract.
Under DL-8 it was removed from the working tree and kept outside the
repository in `~/Code/jiris/m03-draft/` (`m03-draft.patch`, 9 files,
applies cleanly to `aed4672`; `m03-draft-files.tar`, a copy of `app/` and
`tests/` as drafted). The
draft is used as reference material only: tests go in first and are seen
red, then the code, aligned with this report. Developer positions taken
at HG-1 on the contract are applied here: DL-10 (404 body), DL-11
(`/start` while pending), DL-12 (extra 422 rules), 50 race runs, full
return annotations, and the wording "equivalent predicate and SET" for
task 3.3.

## IG-1. Scope and affected surfaces

In scope:

| Surface | Change |
|---|---|
| `app/contracts/__init__.py` | Envelope (R6) and the VisitCompleted payload (TDD §7); `Money` as a 2-place Decimal serialised as a decimal string, floats refused; `Timestamp` serialised as UTC with `Z`; `schema_version = 1`; `new_envelope()` |
| `app/visits/service.py` | `create_visit`, `get_visit`, `request_completion` (the conditional UPDATE of TDD §6.2 plus the outbox INSERT, one transaction), `start_visit`, `cancel_visit`, `mark_missed`; derived `completion_pending` (TDD §5.2) |
| `app/visits/api.py` | Routes of TDD §6.1 for visits; request model `VisitCreate`, response model `VisitOut`; 201, 200, 202, 404, 409 and 422 as contract section 3 with DL-10 to DL-12; one log line per command (contract section 3, Logging) |
| `app/main_api.py` | `create_app()` with a lifespan that opens one pool as `visits_app` from `VISITS_DATABASE_URL`; reads no other database URL |
| `tests/unit/` | `test_contracts.py`, `test_t8_visit_validation.py` |
| `tests/integration/` | `test_visits_api.py`; `conftest.py`: `api_app` no longer depends on `worker`, so API tests run without the worker; T1 requests `worker` explicitly |
| `docs/TDD.md` | §6 state machine and §6.1 (DL-11, DL-12), §6.3 (DL-10) |
| `docs/build-spec/contract.md` | §3 Error shape (DL-10), §5 at completion |

Not touched: `app/billing`, `app/outbox`, `app/main_worker.py`, both
migration chains (no schema change), `docker-compose.yml`, `Dockerfile`,
`init.sql`, `.importlinter`.

Out of scope, binding (module section 5): publishing outbox rows (M04),
`GET /api/billing-records` (M05), applying BillingRecordCreated and
BillingFailed (M06), authentication. Also deferred: the
BillingRecordCreated and BillingFailed payload models and the exchange
name constants, which the draft already held; they go to M05 and M04
(OQ-6, approved).

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M02 complete and committed (`aed4672`), IG-7 written; contract HG-1
  given; OQ-1 and OQ-2 answered (DL-1, DL-6). Met.
- No new package: FastAPI, SQLAlchemy async, asyncpg, Pydantic, httpx and
  pytest-asyncio are already in `uv.lock`.

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | Visit ids and event ids are generated with `uuid.uuid7()` (standard library from Python 3.14); time-ordered ids are harmless for TDD §5 | Switch to `uuid4()`; no schema impact |
| A2 | Under READ COMMITTED, the second concurrent conditional UPDATE waits on the row lock and re-evaluates the predicate after the first COMMIT, so it matches no row | The race test would show two 202 responses; this would reopen D17 (PRD §9 stop condition) |
| A3 | The ORM `update().returning(Visit)` emits one `UPDATE ... WHERE ... RETURNING` statement with the predicate and SET of TDD §6.2 | Checked by reading the emitted SQL once in a test log; fallback is `text()` with the TDD statement verbatim |

Risks:

| Risk | Mitigation |
|---|---|
| The race test passes without real overlap, because two in-process requests could run one after the other | Add a deterministic test: a separate `visits_app` connection holds the row with the same conditional UPDATE in an open transaction; `/complete` is sent and must not answer before that transaction commits; after COMMIT it answers 409 `completion_pending` |
| A 202 is returned before the outbox row is durable | The response body is built inside `async with sessions.begin()`, and returned only after the block commits; the integration test reads the outbox row through a separate connection after the 202 |
| The module criterion "`count(*) FROM visits.outbox WHERE published_at IS NULL` equals 1" is not reliable on the shared session database, where other tests leave rows | Assert the count for the visit under test (`payload->>'visit_id'`); module criterion reworded (OQ-7, approved) |
| Integration tests share one database and one API app per session | Every test creates its own visit; every query filters by its visit id |
| Committing red tests leaves the branch red between two commits | Accepted under DL-8; the branch is merged only after IG-7 |
| Tests that need Completed, Canceled or Missed set the status directly with SQL as `visits_app`, since no API path reaches Completed before M06 | Accepted as test arrangement; documented in the test |

Edge cases covered by tests:

- `/complete` from Scheduled and from In Progress: 202, status unchanged
  (D18), `completion_pending: true`, one outbox row whose `event_id`
  equals `completion_attempt_id` (R1) and whose payload validates as
  VisitCompleted.
- `/complete` from Completed, Canceled, Missed: 409 `invalid_status`, no
  outbox row.
- `/complete` twice, sequentially: 409 `completion_pending`, still one row.
- `/complete` concurrently: one 202, one 409, one row; 50 runs.
- `/complete` after a reset (`completion_requested_at` set to NULL and
  `completion_failure_reason` set by SQL, as M06 will do): 202,
  `completion_failure_reason` cleared, a new attempt id, a second outbox
  row (FR8, Visits side).
- `/cancel`, `/missed` and `/start` while pending: 409
  `completion_pending` (R2, DL-11); status and pending flag unchanged.
- Transitions: `/start` Scheduled only; `/cancel` from Scheduled and In
  Progress; `/missed` from Scheduled only; any other source: 409
  `invalid_status`.
- Unknown id on every route: 404 with `{"detail": "Not Found"}` (DL-10).
  A malformed id in the path: 422 from FastAPI path validation.
- Creation: `rate` 0, negative, more than 2 decimal places, more than 10
  integer digits; `end_date_time` equal to or before `start_date_time`;
  unknown fields: 422 (FR11, DL-12). Naive timestamps: 422 (OQ-5,
  approved).
- Money: `"25"` is returned as `"25.00"`; floats are refused on the wire
  in events.
- The API app starts with `VISITS_DATABASE_URL` only; no
  `BILLING_DATABASE_URL` is read (module criterion on `billing_app`).

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-03` amendments, this report and contract
   §5 and §7a on the feature branch (`docs:`).
1a. Narrow the T1 marker to `raises=WorkerNotReady` (`test:` commit,
   DL-17); suite unchanged at 73 collected, 23 passed, 50 xfailed.
2. Tests (`test:` commit), adapted from the draft to the approved
   positions: 50 race runs; `/start` while pending; 422 for extra places
   and unknown fields; 404 body; plus the lock test, the reset test, the
   configuration test and a log line test. Run the suite and record the
   red result in the IG-7 report: unit tests fail on import of
   `VisitCreate` and the contract models; integration tests fail on the
   missing routes; previous 73 tests unchanged.
3. `app/contracts` (`feat:` commit): unit contract tests green.
4. `app/visits/service.py`, `app/visits/api.py`, `app/main_api.py`,
   `conftest.py` change (`feat:` commit): API tests and T8 validation
   green; full return annotations on every function.
5. Command logging (`feat:` commit, may merge with step 4).
6. Documentation (`docs:` commit): TDD §6, §6.1, §6.3; contract §3
   (DL-10).
7. Validation: full suite from a clean clone; 3.1.6 at 50 of 50;
   `lint-imports`; both `alembic check` (in the suite); T7 still green;
   collected total at least 73 plus the new tests (estimate about 160);
   `git branch --show-current` after every commit.
8. `gate-report-M03-IG-7.md`, module checkboxes, contract §5; stop for
   the developer's approval; then merge per BS-3.

## Questions for HG-1 (contract section 7a)

All four approved by the developer with HG-1 on 2026-11-11 (DL-13 to
DL-16). Also at HG-1: the T1 marker is narrowed to
`raises=WorkerNotReady` (DL-17), and the unverified x86_64 wheels are
recorded as TD-3. The narrowing is committed before the M03 tests.

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-5 | Reject naive (timezone-less) timestamps at creation with 422? TDD stores timestamptz; FR11 does not mention it | Yes: a naive time is ambiguous and would be read in the server's zone |
| OQ-6 | Limit `app.contracts` in M03 to the envelope and VisitCompleted (module task 3.2), deferring BillingRecordCreated, BillingFailed and the exchange constants to M04 to M06? | Yes: follows "implement only the current module" |
| OQ-7 | Reword the module criterion on the outbox count to "for the visit under test"? | Yes: the shared test database makes a global count unreliable |
| OQ-8 | Add the deterministic row-lock test and the reset test to task 3.1? | Yes: both are tests only and prove A2 and FR8 on the Visits side |
